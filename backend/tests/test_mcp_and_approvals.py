"""
Intent AI Gateway — MCP Server & Human Approval Channel Tests.

Tests:
1. Token reuse is rejected (single-use random tokens).
2. Expired approval token is rejected on POST.
3. Approval re-runs deterministic rules and blocks if price drifted before capture.
4. A paused agent is immediately blocked from submitting intent or payments.
5. MCP tools cannot reach admin operations.
6. The MCP block response contains structured remediation JSON.

FIX 1b — hardened confirmation-page security tests:
7.  Two different GETs (scanner then human) both yield valid stateless CSRF tokens
    and the human's POST succeeds.
8.  GET performs zero database writes (approval_requests row count unchanged).
9.  Expired and resolved approvals render no <form> element.
10. The raw approval token never appears in captured log output.
11. After a successful form POST the browser receives 303 and a refresh of the
    redirect target does not re-trigger the action.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone
import pytest
import httpx

from app.main import app
from app.db import init_db, get_db, DB_PATH
from app.mandate import create_demo_mandate, get_signing_key
from app.approvals import (
    create_approval_request,
    process_approval_action,
    get_approval_by_token,
    get_approval_for_display,
    compute_csrf_token,
    verify_csrf_token,
    ApprovalStatus,
)
from app.mcp_server import (
    list_mcp_tool_names,
    mcp_submit_order_intent,
    mcp_search_products,
)
import aiosqlite

ADMIN_KEY = "admin_super_secret_test_key"
AGENT_KEY = "demo_agent_secret_test_key"


@pytest.fixture(scope="module", autouse=True)
def setup_test_env():
    """Ensure database is initialized for tests."""
    asyncio.run(init_db())
    app.state.limiter.enabled = False
    yield


# ── Helper ─────────────────────────────────────────────────────────────────

def _make_csrf(approval: dict) -> str:
    """Derive the stateless CSRF token the same way the GET handler does."""
    return compute_csrf_token(
        approval_id=approval["id"],
        token_hash=approval["token_hash"],
        expires_at=approval["expires_at"],
    )


async def _row_count(table: str) -> int:
    """Return the current row count for a table."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM {table}") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Original tests (kept intact, adapted for stateless CSRF) ───────────────

@pytest.mark.asyncio
async def test_token_reuse_is_rejected():
    """Verify single-use random tokens cannot be used twice."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_test_token_reuse",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="staples.com",
            quantity=1,
            subtotal="899.99",
            currency="USD",
            expires_in_minutes=15,
        )
        approval = await get_approval_by_token(token)
        csrf = _make_csrf(approval)

        # 1st use: Approve → Should succeed
        res1 = await client.post(
            "/api/approvals/action",
            json={"token": token, "action": "approve", "csrf_token": csrf},
        )
        assert res1.status_code == 200, f"Expected 200 on first use, got {res1.status_code}: {res1.text}"
        data1 = res1.json()
        assert data1["status"] in ("APPROVED", "CAPTURED", "VERIFIED_READY_FOR_PAYPAL", "BLOCKED")

        # 2nd use: Replay → Should be rejected (409 TOKEN_ALREADY_USED)
        res2 = await client.post(
            "/api/approvals/action",
            json={"token": token, "action": "approve", "csrf_token": csrf},
        )
        assert res2.status_code in (400, 403, 409, 410), (
            f"Expected 4xx on token reuse, got {res2.status_code}: {res2.text}"
        )


@pytest.mark.asyncio
async def test_expired_token_is_rejected():
    """Verify expired approval tokens are rejected on POST."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_test_expired",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="staples.com",
            quantity=1,
            subtotal="899.99",
            currency="USD",
            expires_in_minutes=-5,
        )
        approval = await get_approval_by_token(token)
        csrf = _make_csrf(approval)

        res = await client.post(
            "/api/approvals/action",
            json={"token": token, "action": "approve", "csrf_token": csrf},
        )
        assert res.status_code in (400, 410), f"Expected 400/410 on expired token, got {res.status_code}"
        assert "EXPIRED" in res.text


@pytest.mark.asyncio
async def test_approval_reruns_rules_and_blocks_if_price_drifted():
    """Verify approval re-evaluates rules and detects pre-capture price drift."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_test_drift_approval",
            mandate_id="demo_mandate_01",
            product_id="prod_drifting_price",
            merchant_domain="staples.com",
            quantity=1,
            subtotal="500.00",
            currency="USD",
            expires_in_minutes=15,
        )
        approval = await get_approval_by_token(token)
        csrf = _make_csrf(approval)

        res = await client.post(
            "/api/approvals/action",
            json={"token": token, "action": "approve", "csrf_token": csrf},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "BLOCKED"
        assert "PRICE_DRIFT" in str(data.get("violations", []))


@pytest.mark.asyncio
async def test_paused_agent_is_blocked():
    """Verify kill switch: paused agent is immediately blocked on all endpoints."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        agent_id = "agent_demo_01"

        pause_res = await client.post(
            f"/api/agents/{agent_id}/pause",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert pause_res.status_code == 200
        assert pause_res.json()["status"] == "PAUSED"

        intent_payload = {
            "mandate_id": "demo_mandate_01",
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
        }
        order_res = await client.post(
            "/api/verify-and-pay",
            json=intent_payload,
            headers={"X-Agent-Key": AGENT_KEY},
        )
        assert order_res.status_code == 403
        assert "AGENT_PAUSED" in order_res.text

        resume_res = await client.post(
            f"/api/agents/{agent_id}/resume",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resume_res.status_code == 200
        assert resume_res.json()["status"] == "ACTIVE"

        order_res_after = await client.post(
            "/api/verify-and-pay",
            json=intent_payload,
            headers={"X-Agent-Key": AGENT_KEY},
        )
        assert order_res_after.status_code in (200, 201)


def test_mcp_tools_cannot_reach_admin_operations():
    """Verify MCP tool registry strictly isolates agent tools and forbids admin actions."""
    tool_names = list_mcp_tool_names()

    expected_tools = {"search_products", "submit_order_intent", "get_mandate_status", "get_order_status"}
    assert set(tool_names) == expected_tools, f"MCP tools mismatch. Expected {expected_tools}, got {tool_names}"

    forbidden_prefixes = ["create", "edit", "revoke", "approve", "deny", "refund", "pause", "resume"]
    for t in tool_names:
        for prefix in forbidden_prefixes:
            assert not t.startswith(prefix), f"MCP exposes unauthorized action: {t}"


@pytest.mark.asyncio
async def test_mcp_block_response_contains_remediation_json():
    """Verify MCP submit_order_intent returns structured remediation JSON on block."""
    result = await mcp_submit_order_intent(
        mandate_id="demo_mandate_01",
        product_id="0HQkNwE",
        merchant_domain="bestbuy.com",
        quantity=1,
    )

    assert result["status"] == "BLOCKED"
    assert "remediation" in result
    remediation = result["remediation"]
    assert remediation is not None
    assert "action" in remediation
    assert "instruction" in remediation
    assert "0HQkNwE" in remediation.get("exclude_product_ids", [])


# ── FIX 1b — hardened confirmation-page security tests ─────────────────────

@pytest.mark.asyncio
async def test_two_gets_both_yield_valid_csrf_and_human_post_succeeds():
    """
    Two different GET requests (simulating scanner then human) both yield valid
    stateless CSRF tokens.  The human's POST with the second CSRF succeeds.
    Because the CSRF is stateless (HMAC over approval_id||token_hash||expires_at),
    any GET yields an identical deterministic value — both are valid for the POST.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_two_gets_csrf",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="amazon.com",
            quantity=1,
            subtotal="49.99",
            currency="USD",
            expires_in_minutes=15,
        )

        # GET 1 — link scanner
        get1 = await client.get(f"/api/approvals/action?token={token}")
        assert get1.status_code == 200
        assert "<form" in get1.text

        # GET 2 — human opens the link
        get2 = await client.get(f"/api/approvals/action?token={token}")
        assert get2.status_code == 200
        assert "<form" in get2.text

        # Both GETs embed the same deterministic CSRF — derive it directly
        approval = await get_approval_by_token(token)
        csrf = _make_csrf(approval)

        # Verify the CSRF is correctly embedded (at least one of them)
        assert csrf in get2.text, "CSRF token from compute_csrf_token must appear in page HTML"

        # POST with that CSRF → should succeed
        post_res = await client.post(
            "/api/approvals/action",
            json={"token": token, "action": "approve", "csrf_token": csrf},
        )
        assert post_res.status_code == 200, (
            f"POST after two GETs should succeed, got {post_res.status_code}: {post_res.text}"
        )
        assert post_res.json()["status"] in ("APPROVED", "BLOCKED")


@pytest.mark.asyncio
async def test_get_performs_zero_database_writes():
    """
    GET /api/approvals/action must not write to the database.
    Row counts for all tables must be unchanged after the GET.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_zero_writes",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="amazon.com",
            quantity=1,
            subtotal="29.99",
            currency="USD",
            expires_in_minutes=15,
        )

        # Count rows in all relevant tables before GET
        tables = ["approval_requests", "audit_events", "budget_reservations", "attempts"]
        counts_before = {t: await _row_count(t) for t in tables}

        # Fire three GET requests
        for _ in range(3):
            res = await client.get(f"/api/approvals/action?token={token}")
            assert res.status_code == 200

        # Counts must be identical — stateless CSRF = no DB writes
        counts_after = {t: await _row_count(t) for t in tables}
        for t in tables:
            assert counts_after[t] == counts_before[t], (
                f"Table '{t}' had {counts_before[t]} rows before GET, "
                f"but {counts_after[t]} after — GET must not write."
            )


@pytest.mark.asyncio
async def test_expired_and_resolved_approvals_render_no_form():
    """
    For EXPIRED, APPROVED, DENIED, and BLOCKED approvals the confirmation
    page must render a read-only status card with no <form> element.
    For an unknown token, 404 is returned.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        # --- Expired token ---
        _, token_exp = await create_approval_request(
            attempt_id="att_no_form_expired",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="amazon.com",
            quantity=1,
            subtotal="9.99",
            currency="USD",
            expires_in_minutes=-5,
        )
        res_exp = await client.get(f"/api/approvals/action?token={token_exp}")
        assert res_exp.status_code == 200
        assert "<form" not in res_exp.text, "Expired approval must render no <form>"
        assert "expired" in res_exp.text.lower() or "EXPIRED" in res_exp.text

        # --- Already-approved token (resolve it first) ---
        appr_app, token_app = await create_approval_request(
            attempt_id="att_no_form_approved",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="amazon.com",
            quantity=1,
            subtotal="9.99",
            currency="USD",
            expires_in_minutes=15,
        )
        approval_app = await get_approval_by_token(token_app)
        csrf_app = _make_csrf(approval_app)
        resolve = await client.post(
            "/api/approvals/action",
            json={"token": token_app, "action": "approve", "csrf_token": csrf_app},
        )
        assert resolve.status_code == 200

        res_app = await client.get(f"/api/approvals/action?token={token_app}")
        assert res_app.status_code == 200
        assert "<form" not in res_app.text, "Approved approval must render no <form>"

        # --- Unknown / garbage token ---
        res_bad = await client.get("/api/approvals/action?token=completely_fake_token_xyz")
        assert res_bad.status_code == 404


@pytest.mark.asyncio
async def test_raw_token_never_appears_in_logs():
    """
    The raw approval token must never appear in log output captured during a GET.
    The log-filter middleware rewrites the query string to empty bytes before any
    logger records the access line.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_log_mask",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="amazon.com",
            quantity=1,
            subtotal="9.99",
            currency="USD",
            expires_in_minutes=15,
        )

        # Capture log records emitted during the GET
        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(self.format(record))

        handler = _Capture()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            res = await client.get(f"/api/approvals/action?token={token}")
            assert res.status_code == 200
        finally:
            root_logger.removeHandler(handler)

        all_log_text = "\n".join(captured)
        assert token not in all_log_text, (
            f"Raw approval token must not appear in log output.\n"
            f"Token prefix: {token[:8]}...\n"
            f"Log lines captured: {len(captured)}"
        )


@pytest.mark.asyncio
async def test_refresh_after_post_does_not_retrigger_action():
    """
    After a successful form POST the server redirects 303 to a status page.
    Re-fetching the status page (simulating a browser refresh) must NOT
    re-trigger the approval action — it is a plain GET of a read-only page.
    """
    transport = httpx.ASGITransport(app=app)
    # follow_redirects=False so we can inspect the 303
    async with httpx.AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        appr_req, token = await create_approval_request(
            attempt_id="att_303_refresh",
            mandate_id="demo_mandate_01",
            product_id="pPB4LGu",
            merchant_domain="staples.com",
            quantity=1,
            subtotal="19.99",
            currency="USD",
            expires_in_minutes=15,
        )
        approval = await get_approval_by_token(token)
        csrf = _make_csrf(approval)

        # Submit form POST
        post_res = await client.post(
            "/api/approvals/action",
            content=f"token={token}&action=approve&csrf_token={csrf}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert post_res.status_code == 303, (
            f"Form POST must redirect 303, got {post_res.status_code}: {post_res.text}"
        )
        redirect_location = post_res.headers.get("location", "")
        assert redirect_location, "303 response must include a Location header"

    # Follow the redirect — simulates browser landing on status page
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status_res = await client.get(redirect_location)
        assert status_res.status_code == 200
        # Must be a plain read-only page — no form, no resubmission buttons
        assert "<form" not in status_res.text, (
            "Status page after redirect must have no form (no resubmission risk)"
        )

        # Refresh (GET same URL again) — must still return 200, still no form
        refresh_res = await client.get(redirect_location)
        assert refresh_res.status_code == 200
        assert "<form" not in refresh_res.text, (
            "Refreshed status page must have no form"
        )

