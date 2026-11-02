import asyncio
import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlencode

from app.auth.settings import auth_settings


class PasswordResetMailer:
    @property
    def configured(self) -> bool:
        return auth_settings.smtp_configured

    async def send(self, recipient: str, token: str) -> None:
        frontend_url = auth_settings.FRONTEND_URL.rstrip("/")
        reset_url = f"{frontend_url}/reset-password?{urlencode({'token': token})}"
        message = self._build_message(recipient, reset_url)
        await asyncio.to_thread(self._send_sync, message)

    @staticmethod
    def _build_message(recipient: str, reset_url: str) -> EmailMessage:
        sender_email = auth_settings.SMTP_FROM_EMAIL
        if sender_email is None:
            raise RuntimeError("SMTP is not configured")

        message = EmailMessage()
        message["Subject"] = "Reset your password"
        message["From"] = formataddr((auth_settings.SMTP_FROM_NAME, str(sender_email)))
        message["To"] = recipient
        if auth_settings.SMTP_REPLY_TO is not None:
            message["Reply-To"] = str(auth_settings.SMTP_REPLY_TO)

        message.set_content(
            "We received a request to reset your password.\n\n"
            f"Reset your password: {reset_url}\n\n"
            f"This link expires in "
            f"{auth_settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes. "
            "If you did not request this change, you can ignore this email."
        )
        escaped_url = html.escape(reset_url, quote=True)
        message.add_alternative(
            "<!doctype html>"
            '<html><body style="font-family:Arial,sans-serif;color:#172126;'
            'line-height:1.6;margin:0;padding:32px">'
            '<div style="max-width:560px;margin:0 auto">'
            '<h1 style="font-size:24px;margin:0 0 16px">Reset your password</h1>'
            "<p>We received a request to reset your password.</p>"
            f'<p style="margin:28px 0"><a href="{escaped_url}" '
            'style="background:#172126;color:#fff;text-decoration:none;'
            'padding:12px 18px;border-radius:6px;display:inline-block">'
            "Reset password</a></p>"
            f"<p>This link expires in "
            f"{auth_settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>"
            "<p>If you did not request this change, you can ignore this email.</p>"
            "</div></body></html>",
            subtype="html",
        )
        return message

    @staticmethod
    def _send_sync(message: EmailMessage) -> None:
        host = auth_settings.SMTP_HOST
        if host is None:
            raise RuntimeError("SMTP is not configured")

        if auth_settings.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(
                host,
                auth_settings.SMTP_PORT,
                timeout=auth_settings.SMTP_TIMEOUT_SECONDS,
                context=ssl.create_default_context(),
            ) as smtp:
                PasswordResetMailer._deliver(smtp, message)
            return

        with smtplib.SMTP(
            host,
            auth_settings.SMTP_PORT,
            timeout=auth_settings.SMTP_TIMEOUT_SECONDS,
        ) as smtp:
            if auth_settings.SMTP_USE_TLS:
                smtp.starttls(context=ssl.create_default_context())
            PasswordResetMailer._deliver(smtp, message)

    @staticmethod
    def _deliver(smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if auth_settings.SMTP_USERNAME is not None:
            smtp.login(
                auth_settings.SMTP_USERNAME,
                auth_settings.SMTP_PASSWORD or "",
            )
        smtp.send_message(message)


password_reset_mailer = PasswordResetMailer()
