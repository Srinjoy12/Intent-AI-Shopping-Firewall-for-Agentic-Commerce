"""Intent Gateway — PayPal Sandbox API client (httpx-based)."""

from __future__ import annotations

import base64
import logging
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
    item_total = f"{float(unit_amount) * quantity:.2f}"

    order_payload = {
        "intent": intent,
        "purchase_units": [
            {
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
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
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
) -> dict:
    """
    Create a PayPal order with payment_source.card for synchronous capture.
    This is the Oct 18 Gate test — if status == "COMPLETED", Outcome A is confirmed.
    """
    settings = get_settings()
    token = await _get_access_token()

    item_total = f"{float(unit_amount) * quantity:.2f}"

    order_payload = {
        "intent": "CAPTURE",
        "payment_source": {
            "card": {
                "number": card_number,
                "expiry": card_expiry,
                "name": card_name,
            }
        },
        "purchase_units": [
            {
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
        ],
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
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


async def capture_order(order_id: str) -> dict:
    """Capture an approved PayPal order."""
    settings = get_settings()
    token = await _get_access_token()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        response.raise_for_status()
        data = response.json()

    logger.info("PayPal capture: order=%s status=%s", order_id, data.get("status"))
    return data


# ── Refund ─────────────────────────────────────────────────────────────────


async def refund_capture(capture_id: str, amount: str | None = None, currency: str = "USD") -> dict:
    """Refund a captured payment."""
    settings = get_settings()
    token = await _get_access_token()

    refund_payload = {}
    if amount is not None:
        refund_payload["amount"] = {
            "currency_code": currency,
            "value": amount,
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paypal_base_url}/v2/payments/captures/{capture_id}/refund",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
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
