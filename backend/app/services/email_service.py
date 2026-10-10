"""Transactional email sending (password reset)."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger(__name__)


def build_password_reset_message(
    to_email: str,
    reset_url: str,
    settings: Settings,
) -> EmailMessage:
    minutes = settings.password_reset_expires_minutes
    message = EmailMessage()
    message["Subject"] = "Reset your Woolly password"
    message["From"] = settings.smtp_from or settings.smtp_username or "noreply@woolly.local"
    message["To"] = to_email
    message.set_content(
        "We received a request to reset the password for your Woolly account.\n\n"
        f"Open this link to choose a new password (it expires in {minutes} minutes):\n\n"
        f"{reset_url}\n\n"
        "If you didn't ask for this, you can ignore this email — your password won't change.\n"
    )
    return message


def send_password_reset_email(to_email: str, reset_url: str, settings: Settings) -> None:
    """Send a reset link, or log it when SMTP isn't configured (local dev)."""
    if not settings.smtp_host:
        logger.info("SMTP is not configured; password reset URL for %s: %s", to_email, reset_url)
        return

    message = build_password_reset_message(to_email, reset_url, settings)
    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                _login_and_send(smtp, message, settings)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.ehlo()
                if settings.smtp_use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                _login_and_send(smtp, message, settings)
        logger.info("Sent a password reset email.")
    except Exception:
        # Never leak send failures to the client — that would reveal whether
        # the address has an account. The user can request another link.
        logger.exception("Failed to send password reset email.")


def _login_and_send(smtp: smtplib.SMTP, message: EmailMessage, settings: Settings) -> None:
    if settings.smtp_username:
        smtp.login(settings.smtp_username, settings.smtp_password)
    smtp.send_message(message)
