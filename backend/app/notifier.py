"""
Intent AI Gateway — Pluggable Human Supervisor Notification Channel.

Supports:
1. ConsoleNotifier (default for live demos, terminal logging, and offline tests)
2. TelegramNotifier (Telegram bot integration via TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID)
3. SMTPNotifier (Transactional email alert via SMTP credentials)
"""

from __future__ import annotations

import abc
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional
import httpx

from app.config import get_settings

logger = logging.getLogger("intent.notifier")


class ApprovalNotifier(abc.ABC):
    """Abstract interface for human approval dispatch."""

    @abc.abstractmethod
    async def send_approval_notification(
        self,
        approval_id: str,
        attempt_id: str,
        mandate_id: str,
        product_id: str,
        product_title: str,
        merchant_domain: str,
        quantity: int,
        subtotal: str,
        currency: str,
        expires_at_iso: str,
        token: str,
        base_url: str = "http://127.0.0.1:8000",
    ) -> bool:
        """Send human approval alert with single-use Approve / Deny action links."""
        pass


class ConsoleNotifier(ApprovalNotifier):
    """Default notifier: prints prominent human approval request to server logs."""

    async def send_approval_notification(
        self,
        approval_id: str,
        attempt_id: str,
        mandate_id: str,
        product_id: str,
        product_title: str,
        merchant_domain: str,
        quantity: int,
        subtotal: str,
        currency: str,
        expires_at_iso: str,
        token: str,
        base_url: str = "http://127.0.0.1:8000",
    ) -> bool:
        # Confirmation page — opens a read-only page, not a direct action
        confirm_url = f"{base_url}/api/approvals/action?token={token}"

        banner = f"""
================================================================================
🔔 [INTENT HUMAN SUPERVISOR APPROVAL REQUIRED]
--------------------------------------------------------------------------------
Approval ID:    {approval_id}
Attempt ID:     {attempt_id}
Mandate ID:     {mandate_id}
Product:        {product_title} ({product_id})
Merchant:       {merchant_domain}
Quantity:       {quantity}
Subtotal:       ${subtotal} {currency}
Expires At:     {expires_at_iso}

🔒 Open the confirmation page (opens a confirmation page — no action on click):
  👉 REVIEW & DECIDE: {confirm_url}
================================================================================
"""
        print(banner)
        logger.warning(
            "APPROVAL_REQUIRED: ID=%s Attempt=%s Subtotal=$%s %s. ConfirmURL=[masked]",
            approval_id, attempt_id, subtotal, currency,
        )
        return True


class TelegramNotifier(ApprovalNotifier):
    """Telegram Bot notifier: dispatches formatted Telegram markdown message."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def send_approval_notification(
        self,
        approval_id: str,
        attempt_id: str,
        mandate_id: str,
        product_id: str,
        product_title: str,
        merchant_domain: str,
        quantity: int,
        subtotal: str,
        currency: str,
        expires_at_iso: str,
        token: str,
        base_url: str = "http://127.0.0.1:8000",
    ) -> bool:
        # Single confirmation URL — opens a read-only confirmation page
        confirm_url = f"{base_url}/api/approvals/action?token={token}"

        text = (
            f"🔔 *INTENT: Human Supervisor Approval Required*\n\n"
            f"• *Product:* `{product_title}` (`{product_id}`)\n"
            f"• *Merchant:* `{merchant_domain}`\n"
            f"• *Quantity:* `{quantity}`\n"
            f"• *Subtotal:* `${subtotal} {currency}`\n"
            f"• *Mandate:* `{mandate_id}`\n"
            f"• *Expires:* `{expires_at_iso}`\n\n"
            f"[🔍 Review & Decide]({confirm_url}) — opens a confirmation page with Approve / Deny buttons."
        )

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.error("Failed to send Telegram approval notification: %s", e)
            return False


class SMTPNotifier(ApprovalNotifier):
    """SMTP email notifier: sends transactional HTML email with action buttons."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        to_email: str,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.to_email = to_email

    async def send_approval_notification(
        self,
        approval_id: str,
        attempt_id: str,
        mandate_id: str,
        product_id: str,
        product_title: str,
        merchant_domain: str,
        quantity: int,
        subtotal: str,
        currency: str,
        expires_at_iso: str,
        token: str,
        base_url: str = "http://127.0.0.1:8000",
    ) -> bool:
        # Single confirmation URL — opens a confirmation page with Approve / Deny buttons
        confirm_url = f"{base_url}/api/approvals/action?token={token}"

        subject = f"[Intent Approval Required] ${subtotal} {currency} at {merchant_domain}"
        html_body = f"""
        <html>
        <body style="font-family: -apple-system, sans-serif; line-height: 1.6; color: #0F172A;">
            <h2>Intent AI Firewall — Purchase Approval Required</h2>
            <p>An autonomous shopping agent has submitted a purchase intent requiring human supervisor authorization.</p>
            <ul>
                <li><strong>Merchant:</strong> {merchant_domain}</li>
                <li><strong>Product:</strong> {product_title} ({product_id})</li>
                <li><strong>Quantity:</strong> {quantity}</li>
                <li><strong>Subtotal:</strong> ${subtotal} {currency}</li>
                <li><strong>Mandate ID:</strong> {mandate_id}</li>
                <li><strong>Expires At:</strong> {expires_at_iso}</li>
            </ul>
            <p style="margin-top: 24px;">
                <a href="{confirm_url}" style="background-color: #3B82F6; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold;">
                    Review &amp; Decide (opens a confirmation page)
                </a>
            </p>
            <p style="font-size: 11px; color: #64748B; margin-top: 24px;">
                This link opens a secure confirmation page — no action is performed on click.
                The page expires in 15 minutes.
            </p>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = self.to_email
        msg.attach(MIMEText(html_body, "html"))

        try:
            # Run blocking SMTP in thread
            import asyncio
            def _send():
                with smtplib.SMTP(self.host, self.port) as server:
                    server.starttls()
                    server.login(self.user, self.password)
                    server.send_message(msg)
            await asyncio.to_thread(_send)
            return True
        except Exception as e:
            logger.error("Failed to send SMTP approval notification: %s", e)
            return False


def get_notifier() -> ApprovalNotifier:
    """Factory to instantiate the configured approval notification channel."""
    import os
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if telegram_token and telegram_chat:
        return TelegramNotifier(telegram_token, telegram_chat)

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    to_email = os.environ.get("NOTIFICATION_EMAIL")
    if smtp_host and smtp_user and smtp_pass and to_email:
        port = int(os.environ.get("SMTP_PORT", 587))
        return SMTPNotifier(smtp_host, port, smtp_user, smtp_pass, to_email)

    return ConsoleNotifier()

