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
