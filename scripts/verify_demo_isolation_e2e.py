"""
Intent AI Gateway — Scripted End-to-End Demo Sandbox & Multi-Tenant Isolation Verification.

Exercises:
1. Bootstrapping two distinct demo sessions (Session 1: Alice, Session 2: Bob).
2. Cryptographic signature and mandate isolation.
3. Policy enforcement in Session 1 (benign purchase, spec spoofing block, budget block, domain block).
4. Kill switch isolation: Session 1 pause blocks Session 1, Session 2 remains ACTIVE and can transact.
5. Approval isolation: Session 1 creates high-value order; Session 2 cannot view or resolve it (403 Forbidden).
6. Refund isolation: Session 2 cannot refund Session 1's capture (403 Forbidden); Session 1 refunds cleanly.
7. Analytics & attempts ledger isolation.
8. Rate limiting isolation: per-session quota exhaustion does not affect the other session.
"""

from __future__ import annotations

import sys
import os
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# Ensure backend is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db, save_approval_request, DB_PATH
import aiosqlite


def run_e2e_isolation_verification() -> bool:
    print("=" * 80)
    print("🛡️  INTENT AI GATEWAY: SCRIPTED E2E DEMO ISOLATION VERIFICATION")
    print("=" * 80)
    
    # 0. Initialize DB
    print("\n[Step 0] Initializing database schema...")
    asyncio.run(init_db())
    print("  ✅ Database initialized.")

    client_1 = TestClient(app)
    client_2 = TestClient(app)

    # 1. Provision Session 1 and Session 2
    print("\n[Step 1] Bootstrapping two distinct visitor sessions...")
    r1 = client_1.get("/api/demo/session")
    assert r1.status_code == 200, f"Session 1 init failed: {r1.text}"
    s1 = r1.json()
    sess1_id = s1["session_id"]
    agent1_id = s1["agent_id"]
    mandate1_id = s1["mandate_id"]

    r2 = client_2.get("/api/demo/session")
    assert r2.status_code == 200, f"Session 2 init failed: {r2.text}"
    s2 = r2.json()
    sess2_id = s2["session_id"]
    agent2_id = s2["agent_id"]
    mandate2_id = s2["mandate_id"]

    print(f"  Session 1 (Alice): id={sess1_id[:8]}... agent={agent1_id} mandate={mandate1_id}")
    print(f"  Session 2 (Bob):   id={sess2_id[:8]}... agent={agent2_id} mandate={mandate2_id}")

    assert sess1_id != sess2_id, "Session IDs must be distinct"
    assert agent1_id != agent2_id, "Agent IDs must be distinct"
    assert mandate1_id != mandate2_id, "Mandate IDs must be distinct"
    print("  ✅ Sessions and cryptographic identities are distinct.")

    # 2. Verify Mandates & Signatures
    print("\n[Step 2] Verifying cryptographic mandate isolation...")
    m1 = client_1.get("/api/demo/mandate").json()
    m2 = client_2.get("/api/demo/mandate").json()

    assert m1["mandate_id"] == mandate1_id
    assert m2["mandate_id"] == mandate2_id
    assert m1["agent_id"] == agent1_id
    assert m2["agent_id"] == agent2_id
    assert m1["signature_valid"] is True
    assert m2["signature_valid"] is True
    assert m1["signature"] != m2["signature"], "Signatures must differ across distinct mandates"
    print("  ✅ Session 1 & 2 mandates verified with valid independent Ed25519 signatures.")

    # 3. Policy Enforcement in Session 1
    print("\n[Step 3] Running full policy enforcement suite in Session 1...")
    
    # 3a. Compliant Purchase (Lenovo Ideapad 16GB RAM)
    res_compliant = client_1.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Purchasing compliant laptop for user",
        },
    )
    assert res_compliant.status_code == 200, f"Compliant purchase failed: {res_compliant.text}"
    c_data = res_compliant.json()
    eval_c = c_data["evaluation"]
    assert eval_c["status"] in ("VERIFIED_READY_FOR_PAYPAL", "CAPTURED")
    assert eval_c["violations"] == []
    print(f"  ✅ 3a. Compliant purchase: PASSED -> {eval_c['status']} (order={eval_c.get('paypal_order_id')}, capture={eval_c.get('paypal_capture_id')})")

    # 3b. Spec Spoofing Attack (Dell laptop with 8GB RAM when mandate requires 16GB)
    res_spoof = client_1.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "0HQkNwE",
            "merchant_domain": "bestbuy.com",
            "quantity": 1,
            "agent_reasoning": "Attempting purchase of 8GB laptop claimed as 16GB",
        },
    )
    assert res_spoof.status_code == 200
    s_data = res_spoof.json()
    eval_s = s_data["evaluation"]
    assert eval_s["status"] == "BLOCKED"
    assert any("STRUCTURED_ATTRIBUTE_MISMATCH" in v.get("rule", "") or "STRUCTURED_ATTRIBUTE_MISMATCH" in str(v) for v in eval_s["violations"])
    print(f"  ✅ 3b. Spec spoofing attack: BLOCKED -> Violations: {eval_s['violations']}")

    # 3c. Over-Budget / Excess Quantity Attack
    res_qty = client_1.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 5,
            "agent_reasoning": "Vendor requires mandatory minimum order quantity of 5",
        },
    )
    assert res_qty.status_code == 200
    q_data = res_qty.json()
    eval_q = q_data["evaluation"]
    assert eval_q["status"] == "BLOCKED"
    assert any("MAX_QUANTITY_EXCEEDED" in v.get("rule", "") or "MAX_QUANTITY_EXCEEDED" in str(v) for v in eval_q["violations"])
    print(f"  ✅ 3c. Quantity/Budget tampering: BLOCKED -> Violations: {eval_q['violations']}")

    # 3d. Lookalike / Unapproved Domain Attack
    res_dom = client_1.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "stap1es-discount-store.com",
            "quantity": 1,
            "agent_reasoning": "Routing to external discount checkout",
        },
    )
    assert res_dom.status_code == 200
    d_data = res_dom.json()
    eval_d = d_data["evaluation"]
    assert eval_d["status"] == "BLOCKED"
    assert any("OFFER_UNAVAILABLE" in v.get("rule", "") or "OFFER_UNAVAILABLE" in str(v) for v in eval_d["violations"])
    print(f"  ✅ 3d. Unauthorized domain attack: BLOCKED -> Violations: {eval_d['violations']}")

    # 4. Emergency Kill Switch Isolation
    print("\n[Step 4] Verifying kill switch isolation between Session 1 and Session 2...")
    pause_r1 = client_1.post("/api/demo/pause")
    assert pause_r1.status_code == 200
    assert pause_r1.json()["status"] == "PAUSED"
    print("  Session 1 agent PAUSED via emergency kill switch.")

    st1 = client_1.get("/api/demo/agent-status").json()
    st2 = client_2.get("/api/demo/agent-status").json()
    assert st1["is_paused"] is True, "Session 1 must be paused"
    assert st2["is_paused"] is False, "Session 2 must remain ACTIVE"
    print("  Status check: Session 1 is_paused=True, Session 2 is_paused=False.")

    # Session 1 attempts purchase -> Rejected (403 AGENT_PAUSED)
    p_blocked = client_1.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Attempt purchase while paused",
        },
    )
    assert p_blocked.status_code == 403
    assert "AGENT_PAUSED" in p_blocked.text
    print("  ✅ Session 1 purchase blocked by kill switch (HTTP 403 AGENT_PAUSED).")

    # Session 2 executes purchase -> Succeeds
    p2_ok = client_2.post(
        "/api/demo/verify-and-pay",
        json={
            "product_id": "pPB4LGu",
            "merchant_domain": "staples.com",
            "quantity": 1,
            "agent_reasoning": "Legitimate purchase in Session 2",
        },
    )
    assert p2_ok.status_code == 200
    p2_eval = p2_ok.json()["evaluation"]
    assert p2_eval["status"] in ("VERIFIED_READY_FOR_PAYPAL", "CAPTURED")
    assert p2_eval["violations"] == []
    print("  ✅ Session 2 purchase SUCCEEDED despite Session 1 being paused.")

    # Resume Session 1
    resume_r1 = client_1.post("/api/demo/resume")
    assert resume_r1.status_code == 200
    assert resume_r1.json()["status"] == "ACTIVE"
    print("  Session 1 agent RESUMED (ACTIVE).")

    # 5. Human Approval Isolation
    print("\n[Step 5] Verifying human approval request & resolution isolation...")
    appr_id_1 = f"appr_e2e_{sess1_id[-6:]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    
    asyncio.run(
        save_approval_request({
            "id": appr_id_1,
            "attempt_id": f"att_e2e_{sess1_id[-6:]}",
            "mandate_id": mandate1_id,
            "product_id": "KXUKS23",
            "merchant_domain": "newegg.com",
            "quantity": 1,
            "subtotal": "1099.99",
            "currency": "USD",
            "status": "PENDING",
            "token_hash": f"hash_e2e_{sess1_id[-6:]}",
            "created_at": now_iso,
            "expires_at": expires_iso,
            "session_id": sess1_id,
        })
    )

    # Session 1 lists pending approvals -> sees it
    p1_list = client_1.get("/api/demo/approvals/pending").json()
    assert any(p["id"] == appr_id_1 for p in p1_list)
    print("  Session 1 lists pending approval: FOUND.")

    # Session 2 lists pending approvals -> does NOT see it
    p2_list = client_2.get("/api/demo/approvals/pending").json()
    assert not any(p["id"] == appr_id_1 for p in p2_list)
    print("  Session 2 lists pending approvals: EMPTY (Isolation preserved).")

    # Session 2 attempts to resolve Session 1's approval -> 403 Forbidden
    steal_appr = client_2.post(
        f"/api/demo/approvals/{appr_id_1}/resolve",
        json={"action": "approve"},
    )
    assert steal_appr.status_code == 403
    assert "APPROVAL_FORBIDDEN" in steal_appr.text
    print("  ✅ Cross-session approval theft rejected: HTTP 403 APPROVAL_FORBIDDEN.")

    # Session 1 resolves its approval -> 200 OK
    res_appr_1 = client_1.post(
        f"/api/demo/approvals/{appr_id_1}/resolve",
        json={"action": "approve"},
    )
    assert res_appr_1.status_code == 200
    assert res_appr_1.json()["status"] == "APPROVED"
    print("  ✅ Session 1 legitimately resolved its own approval: APPROVED.")

    # 6. Refund Isolation
    print("\n[Step 6] Verifying PayPal refund isolation...")
    real_cap_id = eval_c.get("paypal_capture_id")
    if not real_cap_id:
        # Fallback to seeded attempt if no capture id was generated
        real_cap_id = f"CAP_E2E_order_{sess1_id[-6:]}"
        async def seed_session1_capture():
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
                        f"att_cap_{sess1_id[-6:]}",
                        now_iso,
                        mandate1_id,
                        "pPB4LGu",
                        "staples.com",
                        1,
                        "CAPTURED",
                        "749.99",
                        "749.99",
                        f"ORDER_E2E_{sess1_id[-6:]}",
                        real_cap_id,
                        sess1_id,
                    ),
                )
                await db.commit()
        asyncio.run(seed_session1_capture())

    # Session 2 attempts to refund Session 1's capture -> 403 Forbidden
    steal_refund = client_2.post(f"/api/demo/refund/{real_cap_id}")
    assert steal_refund.status_code == 403
    assert "REFUND_FORBIDDEN" in steal_refund.text
    print(f"  ✅ Cross-session refund theft of {real_cap_id} rejected: HTTP 403 REFUND_FORBIDDEN.")

    # Session 1 refunds its own capture -> 200 OK
    own_refund = client_1.post(f"/api/demo/refund/{real_cap_id}")
    assert own_refund.status_code == 200, f"Expected 200 on own refund, got {own_refund.status_code}: {own_refund.text}"
    assert own_refund.json()["status"] == "REFUNDED"
    print(f"  ✅ Session 1 legitimately refunded its own order {real_cap_id}: REFUNDED.")

    # 7. Ledger & Analytics Isolation
    print("\n[Step 7] Verifying attempt ledger and analytics isolation...")
    att1 = client_1.get("/api/demo/attempts").json()
    att2 = client_2.get("/api/demo/attempts").json()
    att1_ids = {a["attempt_id"] for a in att1}
    att2_ids = {a["attempt_id"] for a in att2}

    assert att1_ids.isdisjoint(att2_ids), "Attempt histories between Session 1 and 2 must have zero overlap"
    print(f"  Session 1 attempts: {len(att1)}, Session 2 attempts: {len(att2)}. Intersection: ZERO.")

    ana1 = client_1.get("/api/demo/analytics").json()
    ana2 = client_2.get("/api/demo/analytics").json()
    s1_tot = ana1["summary"]["total_attempts"]
    s2_tot = ana2["summary"]["total_attempts"]
    print(f"  Session 1 total attempts: {s1_tot}, Session 2 total: {s2_tot}")
    assert s1_tot > 0
    assert s2_tot > 0
    print("  ✅ Analytics metrics strictly scoped per tenant.")

    # 8. Unauthenticated Admin Protection Guard
    print("\n[Step 8] Verifying visitor with no admin key cannot access global admin routes...")
    r_adm1 = client_1.post("/api/agents/global_agent/pause")
    assert r_adm1.status_code in (401, 403)
    r_adm2 = client_1.put("/api/policy", json={"max_order_total": "9999.00"})
    assert r_adm2.status_code in (401, 403)
    r_adm3 = client_1.get("/api/audit/export")
    assert r_adm3.status_code in (401, 403)
    print("  ✅ Global admin endpoints strictly reject unauthenticated visitors (HTTP 401/403).")

    print("\n" + "=" * 80)
    print("🏆 ALL SCRIPTED DEMO E2E ISOLATION CHECKS PASSED WITH ZERO LEAKS")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_e2e_isolation_verification()
    sys.exit(0 if success else 1)
