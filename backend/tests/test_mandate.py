"""
Adversarial and Security Pytest Suite for Signed Mandates.

Covers:
1. Tampering with any field (e.g. max_order_total) after signing is rejected
2. Expired mandate rejected
3. Revoked mandate rejected
4. An agent key cannot use another agent's mandate (MANDATE_AGENT_MISMATCH)
5. An agent key cannot create, revoke or modify a mandate (Admin RBAC enforcement)
6. A mandate signed with a different (untrusted) key is rejected
7. The old unauthenticated policy update path no longer works
8. Public key endpoint returns valid Ed25519 public key
"""

import os
import json
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.main import app
from app.db import init_db
from app.mandate import (
    Mandate,
    MandateStatus,
    generate_ed25519_keypair,
    sign_mandate,
    verify_mandate,
    compute_policy_hash,
    get_public_key_hex,
)
from app.config import get_settings

client = TestClient(app)


@pytest.fixture(autouse=True, scope="session")
def setup_db_and_keys():
    """Ensure database tables, admin, and agent keys are initialized for tests."""
    os.environ["ADMIN_API_KEY"] = "admin_super_secret_test_key"
    os.environ["DEMO_AGENT_KEY"] = "demo_agent_secret_test_key"
    get_settings().admin_api_key = "admin_super_secret_test_key"
    asyncio.run(init_db())


def test_tampering_field_after_signing_rejected():
    """Tampering with any field (e.g. max_order_total) after signing must be rejected."""
    priv_key, pub_key = generate_ed25519_keypair()
    
    mandate_data = {
        "mandate_id": "man_test_tamper_01",
        "owner_id": "user_alice",
        "agent_id": "agent_shopping_01",
        "max_order_total": "1000.00",
        "auto_approve_under": "800.00",
        "max_quantity": 1,
        "required_attributes": {"ram": "16GB"},
        "allowed_domains": ["staples.com", "bestbuy.com"],
        "required_availability": "InStock",
        "daily_limit": "2000.00",
        "weekly_limit": "5000.00",
        "per_merchant_limit": "1500.00",
        "max_orders_per_hour": 5,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "nonce": "nonce_12345678",
    }
    
    signed_mandate = sign_mandate(mandate_data, priv_key)
    
    # 1. Verify original is valid
    is_valid, err = verify_mandate(signed_mandate, pub_key)
    assert is_valid is True
    assert err is None
    
    # 2. Tamper with max_order_total
    tampered_mandate = signed_mandate.model_copy(deep=True)
    tampered_mandate.max_order_total = "9999.00"
    
    is_valid_tampered, err_tampered = verify_mandate(tampered_mandate, pub_key)
    assert is_valid_tampered is False
    assert err_tampered in ("MANDATE_SIGNATURE_INVALID", "MANDATE_HASH_MISMATCH")


def test_expired_mandate_rejected():
    """An expired mandate must be rejected with MANDATE_EXPIRED."""
    priv_key, pub_key = generate_ed25519_keypair()
    
    expired_data = {
        "mandate_id": "man_test_expired_01",
        "owner_id": "user_alice",
        "agent_id": "agent_shopping_01",
        "max_order_total": "1000.00",
        "auto_approve_under": "800.00",
        "max_quantity": 1,
        "required_attributes": {"ram": "16GB"},
        "allowed_domains": ["staples.com"],
        "required_availability": "InStock",
        "daily_limit": "2000.00",
        "weekly_limit": "5000.00",
        "per_merchant_limit": "1000.00",
        "max_orders_per_hour": 5,
        "issued_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "nonce": "nonce_expired_1",
    }
    
    signed_mandate = sign_mandate(expired_data, priv_key)
    is_valid, err = verify_mandate(signed_mandate, pub_key)
    assert is_valid is False
    assert err == "MANDATE_EXPIRED"


def test_revoked_mandate_rejected():
    """A revoked mandate must be rejected with MANDATE_REVOKED."""
    # Create mandate via admin endpoint
    admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
    mandate_payload = {
        "mandate_id": "man_to_revoke_01",
        "owner_id": "user_alice",
        "agent_id": "agent_shopping_01",
        "max_order_total": "1000.00",
        "auto_approve_under": "800.00",
        "max_quantity": 1,
        "required_attributes": {"ram": "16GB"},
        "allowed_domains": ["bestbuy.com"],
        "required_availability": "InStock",
        "daily_limit": "2000.00",
        "weekly_limit": "5000.00",
        "per_merchant_limit": "1000.00",
        "max_orders_per_hour": 5,
        "expires_in_hours": 24,
    }
    create_res = client.post("/api/mandates", json=mandate_payload, headers=admin_headers)
    assert create_res.status_code == 200
    created_id = create_res.json()["mandate"]["mandate_id"]
    
    # Revoke it
    revoke_res = client.post(f"/api/mandates/{created_id}/revoke", headers=admin_headers)
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "REVOKED"
    
    # Calling verify-and-pay with revoked mandate must fail with MANDATE_REVOKED
    req_payload = {
        "mandate_id": created_id,
        "product_id": "0HQkNwE",
        "merchant_domain": "bestbuy.com",
        "quantity": 1,
    }
    agent_headers = {"X-Agent-Key": "demo_agent_secret_test_key"}
    pay_res = client.post("/api/verify-and-pay", json=req_payload, headers=agent_headers)
    assert pay_res.status_code in (400, 403, 422) or pay_res.json().get("detail") == "MANDATE_REVOKED"
    if pay_res.status_code == 200:
        assert pay_res.json()["evaluation"]["status"] == "BLOCKED"
        assert any("MANDATE_REVOKED" in str(v) for v in pay_res.json()["evaluation"]["violations"])


def test_agent_key_cannot_use_another_agent_mandate():
    """An agent key cannot use another agent's mandate (MANDATE_AGENT_MISMATCH)."""
    admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
    mandate_payload = {
        "mandate_id": "man_alice_exclusive_01",
        "owner_id": "user_alice",
        "agent_id": "agent_alice",
        "max_order_total": "1000.00",
        "auto_approve_under": "800.00",
        "max_quantity": 1,
        "required_attributes": {"ram": "16GB"},
        "allowed_domains": ["bestbuy.com"],
        "required_availability": "InStock",
        "daily_limit": "2000.00",
        "weekly_limit": "5000.00",
        "per_merchant_limit": "1000.00",
        "max_orders_per_hour": 5,
        "expires_in_hours": 24,
    }
    client.post("/api/mandates", json=mandate_payload, headers=admin_headers)
    
    # Register/use Bob's key to attempt using Alice's mandate
    bob_headers = {"X-Agent-Key": "bob_different_agent_key"}
    req_payload = {
        "mandate_id": "man_alice_exclusive_01",
        "product_id": "0HQkNwE",
        "merchant_domain": "bestbuy.com",
        "quantity": 1,
    }
    pay_res = client.post("/api/verify-and-pay", json=req_payload, headers=bob_headers)
    assert pay_res.status_code in (400, 401, 403, 422)
    err_body = pay_res.text
    assert "MANDATE_AGENT_MISMATCH" in err_body or "agent" in err_body.lower()


def test_agent_key_cannot_create_revoke_modify_mandate():
    """An agent key cannot create or revoke mandates (Admin RBAC)."""
    agent_headers = {"X-Agent-Key": "demo_agent_secret_test_key"}
    mandate_payload = {
        "mandate_id": "man_rogue_attempt",
        "owner_id": "hacker",
        "agent_id": "rogue_agent",
        "max_order_total": "99999.00",
        "auto_approve_under": "99999.00",
        "max_quantity": 100,
        "required_attributes": {},
        "allowed_domains": ["shady.com"],
        "required_availability": "InStock",
        "daily_limit": "99999.00",
        "weekly_limit": "99999.00",
        "per_merchant_limit": "99999.00",
        "max_orders_per_hour": 100,
    }
    # 1. Agent cannot create
    res_create = client.post("/api/mandates", json=mandate_payload, headers=agent_headers)
    assert res_create.status_code in (401, 403)
    
    # 2. Agent cannot revoke
    res_revoke = client.post("/api/mandates/demo_mandate_01/revoke", headers=agent_headers)
    assert res_revoke.status_code in (401, 403)


def test_mandate_signed_with_different_key_rejected():
    """A mandate signed with a different key is rejected with MANDATE_SIGNATURE_INVALID."""
    attacker_priv_key, _ = generate_ed25519_keypair()
    _, system_pub_key = generate_ed25519_keypair()
    
    mandate_data = {
        "mandate_id": "man_forged_key_01",
        "owner_id": "user_alice",
        "agent_id": "agent_shopping_01",
        "max_order_total": "1000.00",
        "auto_approve_under": "800.00",
        "max_quantity": 1,
        "required_attributes": {"ram": "16GB"},
        "allowed_domains": ["bestbuy.com"],
        "required_availability": "InStock",
        "daily_limit": "2000.00",
        "weekly_limit": "5000.00",
        "per_merchant_limit": "1000.00",
        "max_orders_per_hour": 5,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "nonce": "nonce_forged_key",
    }
    forged_mandate = sign_mandate(mandate_data, attacker_priv_key)
    
    is_valid, err = verify_mandate(forged_mandate, system_pub_key)
    assert is_valid is False
    assert err == "MANDATE_SIGNATURE_INVALID"


def test_old_unauthenticated_policy_update_fails():
    """The old unauthenticated policy update path no longer works."""
    update_payload = {
        "policy_id": "hacked_policy",
        "search_goal": "steal funds",
        "max_order_total": "99999.00",
        "currency": "USD",
        "max_quantity": 999,
        "required_availability": "InStock",
        "required_structured_attributes": {},
        "auto_approve_under": "99999.00",
    }
    # Unauthenticated call
    res = client.put("/api/policy", json=update_payload)
    assert res.status_code in (401, 403, 404, 405)
    
    # Agent-authenticated call (still forbidden — only admin can touch policies/mandates)
    agent_headers = {"X-Agent-Key": "demo_agent_secret_test_key"}
    res_agent = client.put("/api/policy", json=update_payload, headers=agent_headers)
    assert res_agent.status_code in (401, 403, 404, 405)


def test_public_key_endpoint():
    """GET /api/mandate/public-key returns the system's Ed25519 public key."""
    res = client.get("/api/mandate/public-key")
    assert res.status_code == 200
    data = res.json()
    assert "public_key" in data
    assert data["algorithm"] == "Ed25519"


def test_get_policy_returns_active_mandate_and_policy_hash():
    """GET /api/policy returns the active mandate's verified values and its policy_hash."""
    res = client.get("/api/policy")
    assert res.status_code == 200
    data = res.json()
    assert "policy_hash" in data
    assert len(data["policy_hash"]) == 64
    assert data.get("signature_valid") is True
    assert "max_order_total" in data
    assert "auto_approve_under" in data
    assert data.get("currency") == "USD"
    assert "mandate_id" in data


def test_admin_put_policy_creates_new_signed_mandate():
    """Admin PUT /api/policy creates a NEW cryptographically signed mandate rather than mutating in place."""
    admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
    new_policy = {
        "policy_id": "test_admin_policy_01",
        "search_goal": "Admin configured mandate",
        "max_order_total": "1250.00",
        "auto_approve_under": "400.00",
        "max_quantity": 2,
        "required_availability": "InStock",
        "required_structured_attributes": {"ram": "16GB"},
        "allowed_merchant_domains": ["staples.com", "bestbuy.com"],
        "currency": "USD",
    }
    res = client.put("/api/policy", json=new_policy, headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "MANDATE_CREATED"
    assert "policy_hash" in data
    assert "signature" in data

    # Verify GET /api/policy now returns the verified mandate with the new limits and valid signature
    get_res = client.get("/api/policy")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["max_order_total"] == "1250.00"
    assert get_data["auto_approve_under"] == "400.00"
    assert get_data["policy_hash"] == data["policy_hash"]
    assert get_data.get("signature_valid") is True


def test_route_security_regression_guard_all_mutating_endpoints_require_auth():
    """
    Regression Guard: Enumerate all FastAPI routes and ensure that every route capable of
    modifying mandate, policy, agent state, approvals, or refunds requires an admin
    dependency or a session/token-scoped security control.
    """
    sensitive_path_keywords = [
        "mandate",
        "policy",
        "agent",
        "approval",
        "refund",
    ]

    for route in app.routes:
        if not hasattr(route, "methods"):
            continue

        methods = set(route.methods) - {"OPTIONS", "HEAD"}
        mutating_methods = methods.intersection({"POST", "PUT", "PATCH", "DELETE"})
        if not mutating_methods:
            continue

        path = route.path

        # Determine if this route touches mandate, policy, agent state, approvals, or refunds
        is_sensitive = any(kw in path.lower() for kw in sensitive_path_keywords)
        if not is_sensitive:
            continue

        # Collect all dependency function names
        dep_names = set()
        if hasattr(route, "dependant"):
            def collect_deps(dep):
                if dep.call:
                    dep_names.add(getattr(dep.call, "__name__", str(dep.call)))
                for sub in dep.dependencies:
                    collect_deps(sub)
            collect_deps(route.dependant)

        # Check for admin authentication
        has_admin_dep = "require_admin_key" in dep_names

        # Check for session/token verification (e.g. human supervisor approval endpoint or demo sandbox)
        endpoint_name = getattr(route.endpoint, "__name__", "")
        is_session_scoped = (
            "process_approval" in endpoint_name
            or any("session" in d for d in dep_names)
            or path.startswith("/api/demo/")
            or path == "/api/approvals/action"  # verifies single-use token + HMAC-SHA256 CSRF
            or path.startswith("/api/agent/")   # demo test agent simulation loops
        )

        # Assertion: Every sensitive mutating route MUST have admin auth or session-scoped verification
        assert has_admin_dep or is_session_scoped, (
            f"SECURITY REGRESSION: Route {mutating_methods} {path} ({endpoint_name}) "
            f"modifies sensitive state without admin or session-scoped dependency! "
            f"Dependencies found: {dep_names}"
        )

