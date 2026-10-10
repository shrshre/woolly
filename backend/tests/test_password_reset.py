"""Unit tests for password-reset token hashing and reset-email content."""

from types import SimpleNamespace

from app.auth.reset_tokens import generate_reset_token, hash_reset_token
from app.services.email_service import build_password_reset_message, send_password_reset_email


class TestResetTokens:
    def test_hash_is_sha256_hex(self):
        digest = hash_reset_token("woolly-reset")
        assert len(digest) == 64
        assert digest == hash_reset_token("woolly-reset")
        assert digest != hash_reset_token("other-token")

    def test_generated_token_hashes_to_its_pair(self):
        raw, hashed = generate_reset_token()
        assert hashed == hash_reset_token(raw)
        assert len(raw) >= 16


class TestResetEmail:
    def test_message_includes_link_and_expiry(self):
        settings = SimpleNamespace(
            smtp_from="woolly@example.com",
            smtp_username="",
            password_reset_expires_minutes=45,
        )
        url = "http://localhost:5173/reset-password?token=abc"
        message = build_password_reset_message("you@example.com", url, settings)
        body = message.get_content()
        assert message["To"] == "you@example.com"
        assert message["From"] == "woolly@example.com"
        assert url in body
        assert "45 minutes" in body

    def test_send_without_smtp_logs_the_url(self, caplog):
        settings = SimpleNamespace(
            smtp_host="",
            smtp_from="",
            smtp_username="",
            password_reset_expires_minutes=60,
        )
        url = "http://localhost:5173/reset-password?token=secret-token"
        with caplog.at_level("INFO"):
            send_password_reset_email("you@example.com", url, settings)
        assert url in caplog.text
        assert "you@example.com" in caplog.text


# Opt in because this exercises real PostgreSQL transaction/row-lock behavior.
# It creates and drops an isolated schema, never touching application tables.
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.auth import routes
from app.config import Settings, get_settings
from app.db.models import User, PasswordResetToken


@pytest.mark.skipif(os.getenv("RUN_POSTGRES_TESTS") != "1", reason="requires PostgreSQL; set RUN_POSTGRES_TESTS=1")
@pytest.mark.parametrize("same_token", [True, False])
def test_concurrent_resets_only_one_succeeds(monkeypatch, same_token):
    engine = create_engine(get_settings().database_url)
    schema = "reset_test_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    sessions = sessionmaker(bind=scoped, expire_on_commit=False)
    barrier = threading.Barrier(2)
    local = threading.local()

    def synchronize_reads(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "password_reset_tokens" in statement and getattr(local, "active", False) and not getattr(local, "read", False):
            local.read = True
            barrier.wait(timeout=10)

    try:
        User.__table__.create(scoped)
        PasswordResetToken.__table__.create(scoped)
        tokens = ["a" * 32, "b" * 32]
        with sessions() as db:
            user = User(email="reset@example.com", password_hash="old")
            db.add(user)
            db.flush()
            for raw in tokens:
                db.add(PasswordResetToken(user_id=user.id, token_hash=hash_reset_token(raw), expires_at=routes._utc_now() + timedelta(minutes=5)))
            db.commit()
            user_id = user.id
        monkeypatch.setattr(routes, "hash_password", lambda password: "hash:" + password)
        monkeypatch.setattr(routes, "create_access_token", lambda *args: "test-jwt")
        event.listen(engine, "after_cursor_execute", synchronize_reads)

        def reset(index):
            local.active = True
            response = Response()
            with sessions() as db:
                try:
                    routes.reset_password(routes.ResetPasswordRequest(token=tokens[0 if same_token else index], password=f"password-{index}"), response, db, Settings())
                    return 200, index, response.headers.get("set-cookie")
                except HTTPException as exc:
                    return exc.status_code, index, response.headers.get("set-cookie")

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reset, [0, 1]))
        assert sorted(status for status, _, _ in results) == [200, 400]
        winner = next(index for status, index, _ in results if status == 200)
        assert all(bool(cookie) == (status == 200) for status, _, cookie in results)
        with sessions() as db:
            assert db.get(User, user_id).password_hash == f"hash:password-{winner}"
            assert all(token.used_at is not None for token in db.query(PasswordResetToken).all())
    finally:
        if event.contains(engine, "after_cursor_execute", synchronize_reads):
            event.remove(engine, "after_cursor_execute", synchronize_reads)
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
