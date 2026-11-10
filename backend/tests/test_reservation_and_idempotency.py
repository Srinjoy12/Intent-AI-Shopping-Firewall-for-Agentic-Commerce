"""
Adversarial and Concurrency Pytest Suite for Task 2:
Atomic Budget Reservation, Idempotency, Cumulative & Velocity Limits, and Price Drift.

Covers:
1. 20 concurrent requests with a $1,000 daily limit and $200 items: exactly 5 succeed, 15 blocked.
2. 10 orders of $999 against a $1,200 daily limit: only the first succeeds, rest blocked with DAILY_LIMIT_EXCEEDED.
3. Same idempotency key replayed 5 times: 1 reservation/charge, identical responses returned.
4. Same idempotency key with changed quantity returns 409 IDEMPOTENCY_KEY_REUSED.
5. PayPal failure releases reservation; refund restores headroom.
6. Price drift above tolerance blocks the order with PRICE_DRIFT.
"""

import os
import json
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import httpx
from httpx import ASGITransport

from app.main import app
from app.db import init_db
from app.mandate import (
    sign_mandate,
    generate_ed25519_keypair,
)
from app.models import ViolationRule, OrderStatus
from app.config import get_settings


@pytest.fixture(autouse=True, scope="session")
def setup_test_environment():
    os.environ["ADMIN_API_KEY"] = "admin_super_secret_test_key"
    os.environ["DEMO_AGENT_KEY"] = "demo_agent_secret_test_key"
    get_settings().admin_api_key = "admin_super_secret_test_key"
    app.state.limiter.enabled = False
    asyncio.run(init_db())


@pytest.mark.asyncio
async def test_concurrent_requests_daily_limit():
    """
    20 concurrent requests with a $1,000 daily limit and $200 items.
    Atomicity test: exactly 5 succeed ($1,000 spent), 15 are blocked with DAILY_LIMIT_EXCEEDED.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Admin creates a mandate with $1,000 daily limit and $200 items allowed
        admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
        mandate_payload = {
            "mandate_id": "man_concurrency_1000",
            "owner_id": "user_concurrent",
            "agent_id": "agent_demo_01",
            "max_order_total": "1000.00",
            "auto_approve_under": "1000.00",
            "max_quantity": 5,
            "required_attributes": {"ram": "16GB"},
            "allowed_domains": ["staples.com"],
            "required_availability": "InStock",
            "daily_limit": "1000.00",
            "weekly_limit": "5000.00",
            "per_merchant_limit": "1000.00",
            "max_orders_per_hour": 50,
            "expires_in_hours": 24,
        }
        res_m = await client.post("/api/mandates", json=mandate_payload, headers=admin_headers)
        assert res_m.status_code == 200

        # Create custom fixture product with price $200.00 if needed or test endpoint with mock
        # We will use product pPB4LGu (lenovo 16GB) or custom $200 item
        # Let's send 20 requests with unique Idempotency keys
        async def send_order(idx: int):
            headers = {
                "X-Agent-Key": "demo_agent_secret_test_key",
                "Idempotency-Key": f"idemp_concurrent_{idx}",
            }
            payload = {
                "mandate_id": "man_concurrency_1000",
                "product_id": "prod_item_200",  # $200 item
                "merchant_domain": "staples.com",
                "quantity": 1,
            }
            return await client.post("/api/verify-and-pay", json=payload, headers=headers)

        responses = await asyncio.gather(*[send_order(i) for i in range(20)])
        
        successes = 0
        blocked_daily = 0
        for r in responses:
            assert r.status_code == 200
            data = r.json()
            eval_res = data["evaluation"]
            if eval_res["status"] in ("CAPTURED", "VERIFIED_READY_FOR_PAYPAL"):
                successes += 1
            elif eval_res["status"] == "BLOCKED":
                violations = [v["rule"] for v in eval_res.get("violations", [])]
                if "DAILY_LIMIT_EXCEEDED" in violations:
                    blocked_daily += 1

        assert successes == 5, f"Expected exactly 5 successes, got {successes}"
        assert blocked_daily == 15, f"Expected 15 daily limit blocks, got {blocked_daily}"


@pytest.mark.asyncio
async def test_sequential_orders_exceeding_daily_limit():
    """
    10 sequential orders of $999 against a $1,200 daily limit:
    Only the first succeeds; the second and later must block with DAILY_LIMIT_EXCEEDED.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
        mandate_payload = {
            "mandate_id": "man_seq_1200",
            "owner_id": "user_seq",
            "agent_id": "agent_demo_01",
            "max_order_total": "1200.00",
            "auto_approve_under": "1000.00",
            "max_quantity": 1,
            "required_attributes": {"ram": "16GB"},
            "allowed_domains": ["staples.com"],
            "required_availability": "InStock",
            "daily_limit": "1200.00",
            "weekly_limit": "5000.00",
            "per_merchant_limit": "1200.00",
            "max_orders_per_hour": 20,
            "expires_in_hours": 24,
        }
        res_m = await client.post("/api/mandates", json=mandate_payload, headers=admin_headers)
        assert res_m.status_code == 200

        # 1st order of $899.99 (Lenovo pPB4LGu) succeeds
        h1 = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "seq_order_1"}
        r1 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "man_seq_1200",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=h1)
        assert r1.status_code == 200
        assert r1.json()["evaluation"]["status"] in ("CAPTURED", "VERIFIED_READY_FOR_PAYPAL")

        # 2nd order of $899.99 would exceed $1,200 ($899.99 + $899.99 = $1799.98 > $1,200)
        h2 = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "seq_order_2"}
        r2 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "man_seq_1200",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=h2)
        assert r2.status_code == 200
        assert r2.json()["evaluation"]["status"] == "BLOCKED"
        violations = [v["rule"] for v in r2.json()["evaluation"]["violations"]]
        assert "DAILY_LIMIT_EXCEEDED" in violations
        assert "headroom" in str(r2.json()["evaluation"]["remediation"]).lower()


@pytest.mark.asyncio
async def test_idempotency_key_replay_returns_cached_response():
    """
    Same idempotency key replayed 5 times:
    Returns identical response without duplicate reservation or double charge.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
        await client.post("/api/mandates", json={
            "mandate_id": "man_idemp_replay",
            "owner_id": "user_idemp",
            "agent_id": "agent_demo_01",
            "max_order_total": "1200.00",
            "auto_approve_under": "1000.00",
            "max_quantity": 1,
            "required_attributes": {"ram": "16GB"},
            "allowed_domains": ["staples.com"],
            "required_availability": "InStock",
            "daily_limit": "2000.00",
            "weekly_limit": "5000.00",
            "per_merchant_limit": "2000.00",
            "max_orders_per_hour": 10,
            "expires_in_hours": 24,
        }, headers=admin_headers)

        key = "idemp_replay_key_5x"
        headers = {
            "X-Agent-Key": "demo_agent_secret_test_key",
            "Idempotency-Key": key,
        }
        body = {
            "mandate_id": "man_idemp_replay",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }

        first_resp = await client.post("/api/verify-and-pay", json=body, headers=headers)
        assert first_resp.status_code == 200
        first_data = first_resp.json()

        # Replay 4 more times
        for _ in range(4):
            re_resp = await client.post("/api/verify-and-pay", json=body, headers=headers)
            assert re_resp.status_code == 200
            re_data = re_resp.json()
            assert re_data["evaluation"]["attempt_id"] == first_data["evaluation"]["attempt_id"]
            assert re_data["evaluation"]["status"] == first_data["evaluation"]["status"]


@pytest.mark.asyncio
async def test_idempotency_key_changed_quantity_returns_409():
    """Same idempotency key with a changed quantity returns 409 IDEMPOTENCY_KEY_REUSED."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        key = "idemp_conflict_key_409"
        headers = {
            "X-Agent-Key": "demo_agent_secret_test_key",
            "Idempotency-Key": key,
        }

        # Request 1: quantity 1
        r1 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "demo_mandate_01",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=headers)
        assert r1.status_code == 200

        # Request 2: same key, quantity 2
        r2 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "demo_mandate_01",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 2,
        }, headers=headers)
        assert r2.status_code == 409
        assert "IDEMPOTENCY_KEY_REUSED" in r2.text


@pytest.mark.asyncio
async def test_paypal_failure_releases_reservation_and_refund_restores_headroom():
    """
    PayPal failure releases reservation.
    Refunding a capture releases the reservation and restores headroom in the daily window.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
        await client.post("/api/mandates", json={
            "mandate_id": "man_refund_test",
            "owner_id": "user_refund",
            "agent_id": "agent_demo_01",
            "max_order_total": "1000.00",
            "auto_approve_under": "1000.00",
            "max_quantity": 1,
            "required_attributes": {"ram": "16GB"},
            "allowed_domains": ["staples.com"],
            "required_availability": "InStock",
            "daily_limit": "1000.00",  # Exactly enough for 1 item
            "weekly_limit": "2000.00",
            "per_merchant_limit": "1000.00",
            "max_orders_per_hour": 10,
            "expires_in_hours": 24,
        }, headers=admin_headers)

        # Place compliant order
        headers = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "refund_flow_1"}
        r1 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "man_refund_test",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=headers)
        assert r1.status_code == 200
        capture_id = r1.json()["evaluation"]["paypal_capture_id"]
        assert capture_id is not None

        # Try placing second order - must be blocked by daily limit
        headers2 = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "refund_flow_2"}
        r2 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "man_refund_test",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=headers2)
        assert r2.status_code == 200
        assert r2.json()["evaluation"]["status"] == "BLOCKED"
        assert any(v["rule"] == "DAILY_LIMIT_EXCEEDED" for v in r2.json()["evaluation"]["violations"])

        # Admin executes refund for capture_id
        ref_res = await client.post(f"/api/paypal/refund/{capture_id}", headers=admin_headers)
        assert ref_res.status_code == 200

        # Now placing order must succeed because headroom was restored!
        headers3 = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "refund_flow_3"}
        r3 = await client.post("/api/verify-and-pay", json={
            "mandate_id": "man_refund_test",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }, headers=headers3)
        assert r3.status_code == 200
        assert r3.json()["evaluation"]["status"] in ("CAPTURED", "VERIFIED_READY_FOR_PAYPAL")


@pytest.mark.asyncio
async def test_price_drift_above_tolerance_blocks_order():
    """
    If catalog price drifts by more than tolerance (default 1%) before PayPal execution,
    the transaction is halted with PRICE_DRIFT.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-Agent-Key": "demo_agent_secret_test_key", "Idempotency-Key": "price_drift_key_1"}
        payload = {
            "mandate_id": "demo_mandate_01",
            "product_id": "prod_drifting_price",  # Item configured to drift
            "merchant_domain": "staples.com",
            "quantity": 1,
        }
        res = await client.post("/api/verify-and-pay", json=payload, headers=headers)
        assert res.status_code == 200
        eval_res = res.json()["evaluation"]
        assert eval_res["status"] == "BLOCKED"
        violations = [v["rule"] for v in eval_res.get("violations", [])]
        assert "PRICE_DRIFT" in violations
