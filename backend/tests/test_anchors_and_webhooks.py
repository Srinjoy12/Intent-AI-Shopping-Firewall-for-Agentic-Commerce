"""
Tests for FIX 5: Anchor the audit chain in PayPal and add webhooks.

Tests first (mock PayPal verification):
1. invalid signature rejected with 400
2. replayed event ID ignored (idempotent 200)
3. REFUNDED restores headroom
4. DENIED releases reservation
5. anchor mismatch is detected
6. valid anchor matches the audit chain
7. GET /api/audit/anchors lists captured orders with matches_chain
"""

import os
import sys
import uuid
import secrets
from decimal import Decimal
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db import (
    init_db,
    record_attempt,
    update_paypal_order,
    update_paypal_capture,
    save_paypal_anchor,
    is_webhook_processed,
    record_processed_webhook,
    DB_PATH,
)
from app.mandate import create_demo_mandate, get_signing_key, sign_mandate
from app.audit import append_audit_event, verify_order_audit_anchor
from app.reservation import (
    reserve_budget_atomic,
    commit_reservation,
    commit_reservation_by_order,
    release_reservation_by_capture,
    release_reservation_by_order,
)
from app.models import GatewayEvaluationResponse, OrderIntentRequest, OrderStatus


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected():
    """POST /api/paypal/webhook must reject unsigned or invalid signature requests with 400."""
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "id": f"WH-{uuid.uuid4().hex[:12]}",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "CAP-123"},
        }
        # Missing signature headers entirely
        res = await client.post("/api/paypal/webhook", json=payload)
        assert res.status_code == 400
        assert "signature" in res.json().get("detail", "").lower()

        # Signature headers present but verification returns False
        headers = {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
            "paypal-transmission-id": "trans_123",
            "paypal-transmission-sig": "invalid_sig",
            "paypal-transmission-time": "2026-11-07T12:00:00Z",
        }
        with patch("app.paypal_client.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = False
            res2 = await client.post("/api/paypal/webhook", json=payload, headers=headers)
            assert res2.status_code == 400
            assert "signature" in res2.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_webhook_replayed_event_id_ignored():
    """POST /api/paypal/webhook must handle replayed event IDs idempotently (HTTP 200)."""
    await init_db()
    event_id = f"WH-{uuid.uuid4().hex[:12]}"
    payload = {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-REPLAY-1",
            "supplementary_data": {"related_ids": {"order_id": "ORD-REPLAY-1"}},
        },
    }
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
        "paypal-transmission-id": "trans_replay",
        "paypal-transmission-sig": "valid_sig",
        "paypal-transmission-time": "2026-11-07T12:00:00Z",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.paypal_client.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True

            # First delivery
            res1 = await client.post("/api/paypal/webhook", json=payload, headers=headers)
            assert res1.status_code == 200
            assert res1.json().get("status") in ("processed", "success")

            # Replayed delivery
            res2 = await client.post("/api/paypal/webhook", json=payload, headers=headers)
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2.get("status") in ("ignored", "already_processed")
            assert data2.get("event_id") == event_id


# ── Webhook Action Tests (REFUNDED & DENIED) ─────────────────────────────────

@pytest.mark.asyncio
async def test_webhook_refunded_restores_headroom():
    """PAYMENT.CAPTURE.REFUNDED webhook restores budget headroom by releasing/refunding reservation."""
    await init_db()
    signing_key = get_signing_key()
    mandate = create_demo_mandate(signing_key)
    mandate.mandate_id = f"mandate_refund_{uuid.uuid4().hex[:8]}"
    mandate.daily_limit = "500.00"
    from datetime import datetime, timezone, timedelta
    mandate.issued_at = datetime.now(timezone.utc).isoformat()
    mandate.expires_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    mandate = sign_mandate(mandate, signing_key)
    from app.db import save_mandate
    await save_mandate(mandate)

    attempt_id = f"att_refund_{uuid.uuid4().hex[:8]}"
    capture_id = f"cap_refund_{uuid.uuid4().hex[:8]}"
    order_id = f"ord_refund_{uuid.uuid4().hex[:8]}"

    # 1. Create a reservation of $400 out of $500 daily limit
    ok, err, _, res_id = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id=attempt_id,
        amount=Decimal("400.00"),
        merchant_domain="staples.com",
    )
    assert ok is True
    await commit_reservation(res_id)

    # Record attempt with capture_id
    eval_resp = GatewayEvaluationResponse(
        attempt_id=attempt_id,
        policy_id=mandate.mandate_id,
        status=OrderStatus.CAPTURED,
        computed_subtotal="400.00",
        paypal_order_id=order_id,
        paypal_capture_id=capture_id,
    )
    req = OrderIntentRequest(
        agent_id=mandate.agent_id,
        mandate_id=mandate.mandate_id,
        product_id="prod_ref_1",
        merchant_domain="staples.com",
        quantity=1,
        expected_unit_price="400.00",
        currency="USD",
    )
    await record_attempt(eval_resp, req)

    # 2. Verify remaining headroom is $100 ($500 - $400) -> new reservation of $200 must fail
    ok_blocked, err_code, _, _ = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id="att_blocked",
        amount=Decimal("200.00"),
        merchant_domain="staples.com",
    )
    assert ok_blocked is False
    assert err_code == "DAILY_LIMIT_EXCEEDED"

    # 3. Simulate PAYMENT.CAPTURE.REFUNDED webhook
    webhook_id = f"WH-REFUND-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": webhook_id,
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {
            "id": f"ref_{uuid.uuid4().hex[:8]}",
            "amount": {"value": "400.00", "currency_code": "USD"},
            "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}"}],
        },
    }
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
        "paypal-transmission-id": "trans_ref",
        "paypal-transmission-sig": "valid_sig",
        "paypal-transmission-time": "2026-11-07T12:00:00Z",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.paypal_client.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            res = await client.post("/api/paypal/webhook", json=payload, headers=headers)
            assert res.status_code == 200

    # 4. Assert headroom is restored: $200 reservation now succeeds!
    ok_after, err_after, _, _ = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id="att_unblocked",
        amount=Decimal("200.00"),
        merchant_domain="staples.com",
    )
    assert ok_after is True


@pytest.mark.asyncio
async def test_webhook_denied_releases_reservation():
    """PAYMENT.CAPTURE.DENIED webhook releases the reservation and updates attempt status."""
    await init_db()
    signing_key = get_signing_key()
    mandate = create_demo_mandate(signing_key)
    mandate.mandate_id = f"mandate_denied_{uuid.uuid4().hex[:8]}"
    mandate.daily_limit = "500.00"
    mandate = sign_mandate(mandate, signing_key)
    from app.db import save_mandate
    await save_mandate(mandate)

    attempt_id = f"att_denied_{uuid.uuid4().hex[:8]}"
    order_id = f"ord_denied_{uuid.uuid4().hex[:8]}"

    # Reserve $450
    ok, _, _, res_id = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id=attempt_id,
        amount=Decimal("450.00"),
        merchant_domain="bestbuy.com",
    )
    assert ok is True

    eval_resp = GatewayEvaluationResponse(
        attempt_id=attempt_id,
        policy_id=mandate.mandate_id,
        status=OrderStatus.VERIFIED_READY_FOR_PAYPAL,
        computed_subtotal="450.00",
        paypal_order_id=order_id,
    )
    req = OrderIntentRequest(
        agent_id=mandate.agent_id,
        mandate_id=mandate.mandate_id,
        product_id="prod_denied_1",
        merchant_domain="bestbuy.com",
        quantity=1,
        expected_unit_price="450.00",
        currency="USD",
    )
    await record_attempt(eval_resp, req)

    # Webhook PAYMENT.CAPTURE.DENIED
    webhook_id = f"WH-DENIED-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": webhook_id,
        "event_type": "PAYMENT.CAPTURE.DENIED",
        "resource": {
            "id": f"cap_den_{uuid.uuid4().hex[:8]}",
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
        "paypal-transmission-id": "trans_den",
        "paypal-transmission-sig": "valid_sig",
        "paypal-transmission-time": "2026-11-07T12:00:00Z",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.paypal_client.verify_webhook_signature", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = True
            res = await client.post("/api/paypal/webhook", json=payload, headers=headers)
            assert res.status_code == 200

    # Reservation must now be RELEASED; another $450 reservation must succeed
    ok_after, _, _, _ = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id="att_denied_restored",
        amount=Decimal("450.00"),
        merchant_domain="bestbuy.com",
    )
    assert ok_after is True


# ── Audit Anchoring Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_anchor_detection_and_mismatch():
    """Verify that verify_order_audit_anchor detects genuine anchors and flags mismatches."""
    await init_db()
    attempt_id = f"att_anchor_{uuid.uuid4().hex[:8]}"
    order_id = f"ord_anchor_{uuid.uuid4().hex[:8]}"

    # Append RESERVATION_CREATED event into audit chain
    ev_res = await append_audit_event(
        "RESERVATION_CREATED",
        {
            "attempt_id": attempt_id,
            "reservation_id": "res_anchor_01",
            "amount": "150.00",
            "merchant_domain": "staples.com",
        },
    )
    genuine_hash = ev_res.event_hash

    # Case 1: Matching anchor
    mock_paypal_order_good = {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": attempt_id,
                "custom_id": genuine_hash,  # Anchored hash!
                "invoice_id": attempt_id,
            }
        ],
    }

    with patch("app.paypal_client.get_order", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_paypal_order_good
        result_good = await verify_order_audit_anchor(order_id)
        assert result_good["valid"] is True
        assert result_good["matches_chain"] is True
        assert result_good["anchored_hash"] == genuine_hash

    # Case 2: Tampered / Mismatched anchor
    tampered_hash = "f" * 64
    mock_paypal_order_bad = {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": attempt_id,
                "custom_id": tampered_hash,
                "invoice_id": attempt_id,
            }
        ],
    }

    with patch("app.paypal_client.get_order", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_paypal_order_bad
        result_bad = await verify_order_audit_anchor(order_id)
        assert result_bad["valid"] is False
        assert result_bad["matches_chain"] is False
        assert "mismatch" in result_bad["error"].lower() or "not found" in result_bad["error"].lower()


@pytest.mark.asyncio
async def test_get_audit_anchors_endpoint():
    """GET /api/audit/anchors lists captured orders and verifies whether each matches the audit chain."""
    await init_db()
    attempt_id = f"att_list_{uuid.uuid4().hex[:8]}"
    order_id = f"ord_list_{uuid.uuid4().hex[:8]}"
    capture_id = f"cap_list_{uuid.uuid4().hex[:8]}"

    # 1. Create authentic audit event
    ev = await append_audit_event(
        "RESERVATION_CREATED",
        {"attempt_id": attempt_id, "amount": "99.00"},
    )

    # 2. Save anchor into database
    await save_paypal_anchor(
        order_id=order_id,
        attempt_id=attempt_id,
        anchored_hash=ev.event_hash,
        invoice_id=attempt_id,
        capture_id=capture_id,
        status="CAPTURED",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/audit/anchors")
        assert res.status_code == 200
        anchors = res.json()
        assert isinstance(anchors, list)
        matching = [a for a in anchors if a.get("order_id") == order_id]
        assert len(matching) == 1
        record = matching[0]
        assert record["capture_id"] == capture_id
        assert record["anchored_hash"] == ev.event_hash
        assert record["matches_chain"] is True


@pytest.mark.asyncio
async def test_verify_audit_anchor_endpoint_via_paypal_api():
    """GET /api/audit/anchors/{order_id}/verify fetches PayPal order and confirms custom_id matches chain."""
    await init_db()
    attempt_id = f"att_verify_ep_{uuid.uuid4().hex[:8]}"
    order_id = f"ord_verify_ep_{uuid.uuid4().hex[:8]}"

    # Authentic audit event
    ev = await append_audit_event(
        "RESERVATION_CREATED",
        {"attempt_id": attempt_id, "amount": "250.00"},
    )
    genuine_hash = ev.event_hash

    mock_paypal_order = {
        "id": order_id,
        "status": "COMPLETED",
        "purchase_units": [
            {
                "reference_id": attempt_id,
                "custom_id": genuine_hash,
                "invoice_id": attempt_id,
            }
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.paypal_client.get_order", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_paypal_order
            res = await client.get(f"/api/audit/anchors/{order_id}/verify")
            assert res.status_code == 200
            data = res.json()
            assert data["valid"] is True
            assert data["matches_chain"] is True
            assert data["anchored_hash"] == genuine_hash
            assert data["order_id"] == order_id

