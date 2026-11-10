"""Intent Gateway — PayPal Sandbox API client (httpx-based)."""

from __future__ import annotations

import base64
import logging
import os
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Token Cache ────────────────────────────────────────────────────────────

_token_cache: dict[str, Any] = {}


async def _get_access_token() -> str:
    """Obtain a PayPal OAuth2 access token (cached until expiry)."""
    import time

    settings = get_settings()
    if not settings.paypal_client_id or not settings.paypal_client_secret:
        raise ValueError("PayPal client_id and client_secret must be configured in .env")

    # Check cache
    if "token" in _token_cache:
        if time.time() < _token_cache.get("expires_at", 0):
            return _token_cache["token"]

    credentials = base64.b64encode(
        f"{settings.paypal_client_id}:{settings.paypal_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()
        data = response.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    logger.info("PayPal access token acquired (expires in %ds)", data.get("expires_in", 0))
    return data["access_token"]


# ── Order Creation ─────────────────────────────────────────────────────────


async def create_order(
    *,
    reference_id: str,
    custom_id: str,
    description: str,
    item_name: str,
    sku: str,
    unit_amount: str,
    currency: str,
    quantity: int,
    intent: str = "CAPTURE",
    invoice_id: str | None = None,
    paypal_request_id: str | None = None,
) -> dict:
    """
    Create a PayPal order via POST /v2/checkout/orders.

    This creates the order with the verified product data — the LLM's
    submitted data was already verified by the 4-rule engine before
    this function is called.
    """
    settings = get_settings()
    token = await _get_access_token()

    # Compute item total
    item_total = f"{Decimal(unit_amount) * quantity:.2f}"

    pu_item = {
        "reference_id": reference_id,
        "custom_id": custom_id,
        "description": description,
        "amount": {
            "currency_code": currency,
            "value": item_total,
            "breakdown": {
                "item_total": {
                    "currency_code": currency,
                    "value": item_total,
                }
            },
        },
        "items": [
            {
                "name": item_name[:127],  # PayPal 127-char limit
                "sku": sku,
                "unit_amount": {
                    "currency_code": currency,
                    "value": unit_amount,
                },
                "quantity": str(quantity),
                "category": "PHYSICAL_GOODS",
            }
        ],
    }
    if invoice_id:
        pu_item["invoice_id"] = invoice_id[:127]

    order_payload = {
        "intent": intent,
        "purchase_units": [pu_item],
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": paypal_request_id or str(uuid.uuid4()),
            },
            json=order_payload,
        )
        response.raise_for_status()
        data = response.json()

    logger.info(
        "PayPal order created: id=%s status=%s",
        data.get("id"),
        data.get("status"),
    )
    return data


# Alias for staging high-value or new-merchant orders pending human 1-click approval
create_order_for_human_approval = create_order


# ── Order Creation with Card (Synchronous Capture Test) ────────────────────


async def create_order_with_card(
    *,
    reference_id: str,
    custom_id: str,
    description: str,
    item_name: str,
    sku: str,
    unit_amount: str,
    currency: str,
    quantity: int,
    card_number: str,
    card_expiry: str,
    card_name: str = "Intent Sandbox Buyer",
    invoice_id: str | None = None,
    paypal_request_id: str | None = None,
) -> dict:
    """
    Create a PayPal order with payment_source.card for synchronous capture.
    This is the Oct 18 Gate test — if status == "COMPLETED", Outcome A is confirmed.
    """
    settings = get_settings()
    token = await _get_access_token()

    item_total = f"{Decimal(unit_amount) * quantity:.2f}"

    pu_item = {
        "reference_id": reference_id,
        "custom_id": custom_id,
        "description": description,
        "amount": {
            "currency_code": currency,
            "value": item_total,
            "breakdown": {
                "item_total": {
                    "currency_code": currency,
                    "value": item_total,
                }
            },
        },
        "items": [
            {
                "name": item_name[:127],
                "sku": sku,
                "unit_amount": {
                    "currency_code": currency,
                    "value": unit_amount,
                },
                "quantity": str(quantity),
                "category": "PHYSICAL_GOODS",
            }
        ],
    }
    if invoice_id:
        pu_item["invoice_id"] = invoice_id[:127]

    order_payload = {
        "intent": "CAPTURE",
        "payment_source": {
            "card": {
                "number": card_number,
                "expiry": card_expiry,
                "name": card_name,
            }
        },
        "purchase_units": [pu_item],
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": paypal_request_id or str(uuid.uuid4()),
            },
            json=order_payload,
        )
        response.raise_for_status()
        data = response.json()

    logger.info(
        "PayPal card order: id=%s status=%s",
        data.get("id"),
        data.get("status"),
    )
    return data


# ── Capture ────────────────────────────────────────────────────────────────


async def capture_order(order_id: str, paypal_request_id: str | None = None) -> dict:
    """Capture an approved PayPal order."""
    settings = get_settings()
    token = await _get_access_token()

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": paypal_request_id or str(uuid.uuid4()),
            },
        )
        response.raise_for_status()
        data = response.json()

    logger.info("PayPal capture: order=%s status=%s", order_id, data.get("status"))
    return data


# ── Refund ─────────────────────────────────────────────────────────────────


async def refund_capture(
    capture_id: str,
    amount: str | None = None,
    currency: str = "USD",
    paypal_request_id: str | None = None,
) -> dict:
    """Refund a captured payment."""
    settings = get_settings()
    token = await _get_access_token()

    refund_payload = {}
    if amount is not None:
        refund_payload["amount"] = {
            "currency_code": currency,
            "value": amount,
        }

    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/payments/captures/{capture_id}/refund",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": str(uuid.uuid4()),
            },
            json=refund_payload,
        )
        response.raise_for_status()
        data = response.json()

    logger.info("PayPal refund: capture=%s status=%s", capture_id, data.get("status"))
    return data


# ── Health Check ───────────────────────────────────────────────────────────


async def check_paypal_health() -> bool:
    """Check if PayPal credentials are valid by getting a token."""
    try:
        await _get_access_token()
        return True
    except Exception as e:
        logger.warning("PayPal health check failed: %s", e)
        return False


# ── Order Lookup & Webhook Verification ────────────────────────────────────

async def get_order(order_id: str) -> dict[str, Any]:
    """Fetch order details from PayPal Sandbox API."""
    settings = get_settings()
    token = await _get_access_token()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.paypal_base_url}/v2/checkout/orders/{order_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        return response.json()


async def verify_webhook_signature(
    headers: dict[str, str],
    body: dict[str, Any],
    webhook_id: str | None = None,
) -> bool:
    """
    Validate PayPal webhook signature using POST /v1/notifications/verify-webhook-signature.
    Returns True if verification_status is 'SUCCESS', otherwise False.
    """
    settings = get_settings()
    wh_id = webhook_id or getattr(settings, "paypal_webhook_id", "") or os.environ.get("PAYPAL_WEBHOOK_ID", "")
    if not wh_id:
        logger.warning("PAYPAL_WEBHOOK_ID is not configured in environment or settings")
        return False

    # Extract required headers (case-insensitive)
    lower_headers = {k.lower(): v for k, v in headers.items()}
    auth_algo = lower_headers.get("paypal-auth-algo")
    cert_url = lower_headers.get("paypal-cert-url")
    transmission_id = lower_headers.get("paypal-transmission-id")
    transmission_sig = lower_headers.get("paypal-transmission-sig")
    transmission_time = lower_headers.get("paypal-transmission-time")

    if not all([auth_algo, cert_url, transmission_id, transmission_sig, transmission_time]):
        logger.warning("Missing required PayPal webhook headers for signature verification")
        return False

    token = await _get_access_token()
    verify_payload = {
        "auth_algo": auth_algo,
        "cert_url": cert_url,
        "transmission_id": transmission_id,
        "transmission_sig": transmission_sig,
        "transmission_time": transmission_time,
        "webhook_id": wh_id,
        "webhook_event": body,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v1/notifications/verify-webhook-signature",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=verify_payload,
        )
        if response.status_code != 200:
            logger.error("PayPal webhook verification returned error status %d: %s", response.status_code, response.text)
            return False

        result = response.json()
        return result.get("verification_status") == "SUCCESS"

