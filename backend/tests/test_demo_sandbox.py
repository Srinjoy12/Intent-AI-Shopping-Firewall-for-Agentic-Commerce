"""
Intent AI Gateway — Demo Sandbox and Multi-Tenant Isolation Test Suite.

Verifies:
1. Session A cannot pause, approve, refund, or read Session B's resources.
2. A visitor with no admin key cannot call any admin endpoint.
3. The built bundle contains no secrets (runs check_bundle_secrets.sh).
4. Per-session rate limit triggers at 31 requests, and a different session is unaffected.
5. Expired sandbox is rejected (410 Gone) and cleaned up from the database.
"""

import os
import subprocess
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import (
    init_db,
    get_demo_session,
    save_demo_session,
    cleanup_expired_demo_sessions,
    record_attempt,
    save_approval_request,
)
from app.session import sign_session_id, COOKIE_NAME


@pytest.fixture(autouse=True, scope="module")
def setup_db():
    asyncio.run(init_db())


def test_built_bundle_contains_no_secrets():
    """Requirement: The built bundle contains no secrets (run scripts/check_bundle_secrets.sh in a test)."""
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts/check_bundle_secrets.sh"))
    assert os.path.exists(script_path), f"Script {script_path} does not exist"

    result = subprocess.run([script_path], capture_output=True, text=True)
    print("Bundle secrets audit output:\n", result.stdout)
    if result.stderr:
        print("Bundle secrets audit error:\n", result.stderr)
    assert result.returncode == 0, f"check_bundle_secrets.sh failed: {result.stdout}\n{result.stderr}"


def test_visitor_with_no_admin_key_cannot_call_any_admin_endpoint():
    """Requirement: A visitor with no admin key cannot call any admin endpoint."""
    client = TestClient(app)

    # 1. Pause agent (Admin kill switch)
    r1 = client.post("/api/agents/agent_demo_01/pause")
    assert r1.status_code in (401, 403), f"Expected 401 or 403, got {r1.status_code}: {r1.text}"

    # 2. Resume agent
    r2 = client.post("/api/agents/agent_demo_01/resume")
    assert r2.status_code in (401, 403), f"Expected 401 or 403, got {r2.status_code}: {r2.text}"

    # 3. Create mandate
    r3 = client.post("/api/mandates", json={"owner_id": "test", "agent_id": "agent_demo_01", "max_order_total": "100.00"})
    assert r3.status_code in (401, 403), f"Expected 401 or 403, got {r3.status_code}: {r3.text}"

    # 4. Revoke mandate
    r4 = client.post("/api/mandates/demo_mandate_01/revoke")
    assert r4.status_code in (401, 403), f"Expected 401 or 403, got {r4.status_code}: {r4.text}"

    # 5. Update policy (issue new mandate)
    r5 = client.put("/api/policy", json={"max_order_total": "500.00"})
    assert r5.status_code in (401, 403), f"Expected 401 or 403, got {r5.status_code}: {r5.text}"

    # 6. Capture PayPal order
    r6 = client.post("/api/paypal/capture/ORDER_TEST_123")
    assert r6.status_code in (401, 403), f"Expected 401 or 403, got {r6.status_code}: {r6.text}"

    # 7. Refund PayPal capture
    r7 = client.post("/api/paypal/refund/CAP_TEST_123")
    assert r7.status_code in (401, 403), f"Expected 401 or 403, got {r7.status_code}: {r7.text}"

    # 8. Resolve approval by ID
    r8 = client.post("/api/approvals/appr_test/resolve", json={"action": "approve"})
    assert r8.status_code in (401, 403), f"Expected 401 or 403, got {r8.status_code}: {r8.text}"

    # 9. Export audit manifest
    r9 = client.get("/api/audit/export")
    assert r9.status_code in (401, 403), f"Expected 401 or 403, got {r9.status_code}: {r9.text}"


def test_session_isolation_a_cannot_touch_b_resources():
    """
    Requirement: Session A cannot pause, approve, refund, or read Session B's resources.
    """
    client_a = TestClient(app)
    client_b = TestClient(app)

    # 1. Bootstrap Session A and Session B
    res_a = client_a.get("/api/demo/session")
    assert res_a.status_code == 200
    data_a = res_a.json()
    session_a_id = data_a["session_id"]
    agent_a_id = data_a["agent_id"]
    mandate_a_id = data_a["mandate_id"]

    res_b = client_b.get("/api/demo/session")
    assert res_b.status_code == 200
    data_b = res_b.json()
    session_b_id = data_b["session_id"]
    agent_b_id = data_b["agent_id"]
    mandate_b_id = data_b["mandate_id"]

    assert session_a_id != session_b_id
    assert agent_a_id != agent_b_id
    assert mandate_a_id != mandate_b_id

    # 2. Mandate Read Isolation
    man_a = client_a.get("/api/demo/mandate").json()
    man_b = client_b.get("/api/demo/mandate").json()
    assert man_a["mandate_id"] == mandate_a_id
    assert man_b["mandate_id"] == mandate_b_id
    assert man_a["session_id"] == session_a_id
    assert man_b["session_id"] == session_b_id

    # 3. Kill Switch Isolation: Session A pauses its agent; Session B is unaffected
    pause_res_a = client_a.post("/api/demo/pause")
    assert pause_res_a.status_code == 200
    assert pause_res_a.json()["status"] == "PAUSED"

    status_a = client_a.get("/api/demo/agent-status").json()
    assert status_a["is_paused"] is True

    status_b = client_b.get("/api/demo/agent-status").json()
    assert status_b["is_paused"] is False, "Session A pause must NOT affect Session B"

    # Session B can still execute verify-and-pay
    pay_b = client_b.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Session B test purchase",
        },
    )
    assert pay_b.status_code == 200

    # Session A is blocked by its own pause
    pay_a = client_a.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Session A test purchase while paused",
        },
    )
    assert pay_a.status_code == 403
    assert "AGENT_PAUSED" in pay_a.text

    # Resume Session A
    resume_res_a = client_a.post("/api/demo/resume")
    assert resume_res_a.status_code == 200
    assert resume_res_a.json()["status"] == "ACTIVE"

    # 4. Attempt Log & Analytics Read Isolation
    # Session B has 1 attempt; Session A has none yet (the blocked one was rejected before attempt record)
    attempts_b = client_b.get("/api/demo/attempts").json()
    attempts_a = client_a.get("/api/demo/attempts").json()
    b_attempt_ids = [att["attempt_id"] for att in attempts_b]
    for att in attempts_a:
        assert att["attempt_id"] not in b_attempt_ids, "Session A must not read Session B's attempts"

    # 5. Approval Isolation: Session A creates an order requiring human approval
    # Seed an approval request directly belonging to Session A
    appr_id_a = f"appr_sess_a_{session_a_id[-6:]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    asyncio.run(
        save_approval_request({
            "id": appr_id_a,
            "attempt_id": f"att_a_{session_a_id[-6:]}",
            "mandate_id": mandate_a_id,
            "product_id": "KXUKS23",
            "merchant_domain": "newegg.com",
            "quantity": 1,
            "subtotal": "1099.99",
            "currency": "USD",
            "status": "PENDING",
            "token_hash": f"hash_a_{session_a_id[-6:]}",
            "created_at": now_iso,
            "expires_at": expires_iso,
            "session_id": session_a_id,
        })
    )

    # Session A sees its pending approval
    pending_a = client_a.get("/api/demo/approvals/pending").json()
    assert any(p["id"] == appr_id_a for p in pending_a)

    # Session B does NOT see Session A's pending approval
    pending_b = client_b.get("/api/demo/approvals/pending").json()
    assert not any(p["id"] == appr_id_a for p in pending_b), "Session B must not see Session A's approval"

    # Session B attempts to resolve Session A's approval -> must be rejected (403 Forbidden)
    steal_res = client_b.post(
        f"/api/demo/approvals/{appr_id_a}/resolve",
        json={"action": "approve"},
    )
    assert steal_res.status_code == 403, f"Expected 403 when Session B resolves Session A approval, got {steal_res.status_code}"
    assert "APPROVAL_FORBIDDEN" in steal_res.text

    # Session A can resolve its own approval
    resolve_a = client_a.post(
        f"/api/demo/approvals/{appr_id_a}/resolve",
        json={"action": "deny"},
    )
    assert resolve_a.status_code == 200
    assert resolve_a.json()["status"] == "DENIED"

    # 6. Refund Isolation: Session B attempts to refund an order belonging to Session A
    fake_cap_id = f"CAP_SBX_fake_order_a"
    # Seed an attempt belonging to Session A with that capture
    import aiosqlite
    from app.db import DB_PATH
    async def seed_session_attempt():
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO attempts (
                    attempt_id, timestamp, policy_id, product_id, merchant_domain,
                    quantity, status, unit_price, computed_subtotal,
                    paypal_order_id, paypal_capture_id, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"att_cap_{session_a_id[-6:]}",
                    now_iso,
                    mandate_a_id,
                    "pPB4LGu",
                    "staples.com",
                    1,
                    "CAPTURED",
                    "749.99",
                    "749.99",
                    "ORDER_A_123",
                    fake_cap_id,
                    session_a_id,
                ),
            )
            await db.commit()
    asyncio.run(seed_session_attempt())

    # Session B tries to refund Session A's capture -> rejected with 403 Forbidden
    steal_refund = client_b.post(f"/api/demo/refund/{fake_cap_id}")
    assert steal_refund.status_code == 403, f"Expected 403 when Session B refunds Session A capture, got {steal_refund.status_code}"
    assert "REFUND_FORBIDDEN" in steal_refund.text

    # Session A refunds its own capture -> succeeds
    refund_a = client_a.post(f"/api/demo/refund/{fake_cap_id}")
    assert refund_a.status_code == 200
    assert refund_a.json()["status"] == "REFUNDED"


def test_per_session_rate_limit_triggers_and_other_session_unaffected():
    """
    Requirement:
    - per-session rate limit triggers (max 30 requests per session per hour)
    - a different session is unaffected
    """
    client_x = TestClient(app)
    client_y = TestClient(app)

    # Bootstrap Session X and Session Y
    rx = client_x.get("/api/demo/session")
    assert rx.status_code == 200
    ry = client_y.get("/api/demo/session")
    assert ry.status_code == 200

    # Exhaust Session X's remaining quota up to 30 requests
    # Request 1 was already used during bootstrap
    for i in range(2, 31):
        res = client_x.get("/api/demo/session")
        assert res.status_code == 200, f"Request {i} for Session X failed with {res.status_code}"

    # Request 31 for Session X must trigger HTTP 429 Too Many Requests
    blocked_res = client_x.get("/api/demo/session")
    assert blocked_res.status_code == 429, f"Expected 429 for 31st request, got {blocked_res.status_code}: {blocked_res.text}"
    assert "rate limit exceeded" in blocked_res.text.lower()

    # Session Y is unaffected and can execute cleanly
    unaffected_res = client_y.get("/api/demo/session")
    assert unaffected_res.status_code == 200, f"Session Y must not be affected by Session X rate limit, got {unaffected_res.status_code}"


def test_expired_sandbox_is_rejected_and_cleaned_up():
    """
    Requirement: Expired sandbox is rejected (410 Gone) and cleaned up.
    """
    client = TestClient(app)

    # 1. Bootstrap new session
    init_res = client.get("/api/demo/session")
    assert init_res.status_code == 200
    session_id = init_res.json()["session_id"]

    # 2. Artificially expire the session in the database
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    session_record = asyncio.run(get_demo_session(session_id))
    assert session_record is not None
    session_record["expires_at"] = past_iso
    asyncio.run(save_demo_session(session_record))

    # 3. Request with expired cookie must return HTTP 410 Gone
    expired_res = client.get("/api/demo/session")
    assert expired_res.status_code == 410, f"Expected 410 Gone for expired session, got {expired_res.status_code}: {expired_res.text}"
    assert "SANDBOX_EXPIRED" in expired_res.text

    # 4. Verify session record is cleaned up from the database
    cleaned_record = asyncio.run(get_demo_session(session_id))
    assert cleaned_record is None, "Expired session must be cleaned up from database upon rejection"

    # 5. Verify background cleanup task removes any lingering expired sessions
    lingering_id = "sess_lingering_expired"
    asyncio.run(
        save_demo_session({
            "session_id": lingering_id,
            "agent_id": "agent_lingering",
            "mandate_id": "mandate_lingering",
            "created_at": past_iso,
            "expires_at": past_iso,
            "last_active_at": past_iso,
            "request_count": 5,
            "window_start": past_iso,
        })
    )
    cleaned_count = asyncio.run(cleanup_expired_demo_sessions())
    assert cleaned_count >= 1, f"Expected at least 1 session swept, got {cleaned_count}"
    assert asyncio.run(get_demo_session(lingering_id)) is None


def test_demo_mandate_expiry_and_session_scoped_ledger():
    """
    Phase 3 Demo Correctness Verification:
    1. An expired mandate in a demo session rejects order attempts with HTTP 400 MANDATE_EXPIRED.
    2. Session-scoped ledger queries strictly isolate attempts per session_id.
    """
    from app.db import get_mandate_by_id, save_mandate

    client = TestClient(app)
    sess_res = client.get("/api/demo/session")
    assert sess_res.status_code == 200
    sess_data = sess_res.json()
    mandate_id = sess_data["mandate_id"]
    session_id = sess_data["session_id"]

    # 1. Fetch mandate and artificially set expires_at into the past
    mandate = asyncio.run(get_mandate_by_id(mandate_id))
    assert mandate is not None
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    mandate.expires_at = past_iso
    asyncio.run(save_mandate(mandate, session_id=session_id))

    # 2. Attempt verify-and-pay with the expired mandate
    blocked_pay = client.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Attempt with expired mandate",
        },
    )
    assert blocked_pay.status_code == 400, f"Expected 400 for expired mandate, got {blocked_pay.status_code}: {blocked_pay.text}"
    assert "MANDATE_EXPIRED" in blocked_pay.text

    # 3. Verify session-scoped ledger returns only caller session records
    attempts = client.get("/api/demo/attempts").json()
    for att in attempts:
        assert att.get("session_id") == session_id, f"Cross-session leak: attempt {att} not owned by {session_id}"
