"""
Intent AI Gateway — Comprehensive Automated Pytest Suite.

Covers:
1. Rule 1: Merchant Domain & Availability verification
2. Rule 2: Structured Attributes (exact matching, normalization, fail-closed on missing keys)
3. Rule 3: Quantity limits & budget computation math
4. Rule 4: PayPal routing (under auto-approve threshold vs manual approval)
5. Rate Limiter Circuit Breaker
6. FastAPI HTTP Endpoints via TestClient
"""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.models import (
    OrderIntentRequest,
    SpendingPolicy,
    OrderStatus,
    ViolationRule,
    RemediationAction,
)
from app.engine import verify_order_intent
from app.rate_limiter import daily_counter
from app.main import app


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_policy() -> SpendingPolicy:
    return SpendingPolicy(
        policy_id="test_policy_01",
        search_goal="Find a 16GB developer laptop under $1000",
        max_order_total="1000.00",
        currency="USD",
        max_quantity=1,
        allowed_merchant_domains=["staples.com", "bestbuy.com", "newegg.com"],
        required_availability="in_stock",
        required_structured_attributes={"ram": "16GB"},
        auto_approve_under="1000.00",
    )


@pytest.fixture
def mock_valid_product() -> dict:
    return {
        "id": "prod_valid_16gb",
        "title": "Lenovo IdeaPad Slim 5i - 16GB RAM",
        "structured_attributes": {
            "ram": "16 GB",
            "storage-capacity": "512 GB",
        },
        "offers": [
            {
                "merchant_domain": "staples.com",
                "price": "899.99",
                "currency": "USD",
                "availability": "in_stock",
            }
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test Rule 1: Domain & Availability Verification
# ─────────────────────────────────────────────────────────────────────────────

def test_rule_1_merchant_domain_not_found(base_policy, mock_valid_product):
    """Rule 1 must block if the requested merchant domain has no offer."""
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id="prod_valid_16gb",
        merchant_domain="shady-reseller.io",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=mock_valid_product)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.OFFER_UNAVAILABLE for v in evaluation.violations)
    assert "shady-reseller.io" in str(evaluation.violations)


def test_rule_1_merchant_out_of_stock(base_policy):
    """Rule 1 must block if the merchant offer is out of stock."""
    prod = {
        "id": "prod_oos",
        "title": "Laptop Out of Stock",
        "structured_attributes": {"ram": "16GB"},
        "offers": [
            {
                "merchant_domain": "staples.com",
                "price": "850.00",
                "currency": "USD",
                "availability": "out_of_stock",
            }
        ],
    }
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id="prod_oos",
        merchant_domain="staples.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=prod)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.OFFER_UNAVAILABLE for v in evaluation.violations)


# ─────────────────────────────────────────────────────────────────────────────
# Test Rule 2: Structured Attributes & Fail-Closed Behavior
# ─────────────────────────────────────────────────────────────────────────────

def test_rule_2_attribute_mismatch_blocks(base_policy):
    """Rule 2 must block when product spec (e.g. 8GB RAM) does not match policy (16GB)."""
    prod_8gb = {
        "id": "prod_dell_8gb",
        "title": "Dell Touchscreen Laptop - 8GB",
        "structured_attributes": {"ram": "8 GB"},
        "offers": [
            {
                "merchant_domain": "bestbuy.com",
                "price": "749.99",
                "currency": "USD",
                "availability": "in_stock",
            }
        ],
    }
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id="prod_dell_8gb",
        merchant_domain="bestbuy.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=prod_8gb)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.STRUCTURED_ATTRIBUTE_MISMATCH for v in evaluation.violations)
    assert evaluation.remediation is not None
    assert evaluation.remediation.action == RemediationAction.SWITCH_PRODUCT
    assert "prod_dell_8gb" in evaluation.remediation.exclude_product_ids


def test_rule_2_unverifiable_attribute_fails_closed(base_policy):
    """Rule 2 must FAIL-CLOSED if required key is missing from structured_attributes."""
    prod_missing_ram = {
        "id": "prod_no_ram_attr",
        "title": "Unbranded Laptop Without RAM Spec",
        "structured_attributes": {"color": "silver"},
        "offers": [
            {
                "merchant_domain": "bestbuy.com",
                "price": "697.98",
                "currency": "USD",
                "availability": "in_stock",
            }
        ],
    }
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id="prod_no_ram_attr",
        merchant_domain="bestbuy.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=prod_missing_ram)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.UNVERIFIABLE_ATTRIBUTE for v in evaluation.violations)


def test_rule_2_attribute_normalization_succeeds(base_policy, mock_valid_product):
    """Rule 2 normalizes whitespace: '16 GB' in product matches '16GB' in policy."""
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id=mock_valid_product["id"],
        merchant_domain="staples.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=mock_valid_product)

    attr_violations = [
        v for v in evaluation.violations
        if v.rule in (ViolationRule.STRUCTURED_ATTRIBUTE_MISMATCH, ViolationRule.UNVERIFIABLE_ATTRIBUTE)
    ]
    assert len(attr_violations) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test Rule 3: Quantity Limits & Budget Math
# ─────────────────────────────────────────────────────────────────────────────

def test_rule_3_max_quantity_exceeded(base_policy, mock_valid_product):
    """Rule 3 blocks if agent requests more than policy.max_quantity (e.g. quantity=3 > 1)."""
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id=mock_valid_product["id"],
        merchant_domain="staples.com",
        quantity=3,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=mock_valid_product)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.MAX_QUANTITY_EXCEEDED for v in evaluation.violations)
    assert any(v.rule == ViolationRule.BUDGET_EXCEEDED for v in evaluation.violations)
    assert evaluation.remediation.action == RemediationAction.REDUCE_QUANTITY
    assert evaluation.remediation.allowed_quantity == 1


def test_rule_3_budget_exceeded_single_item(base_policy):
    """Rule 3 blocks if product unit price exceeds max_order_total."""
    expensive_prod = {
        "id": "prod_expensive",
        "title": "Workstation Laptop",
        "structured_attributes": {"ram": "16GB"},
        "offers": [
            {
                "merchant_domain": "newegg.com",
                "price": "2499.00",
                "currency": "USD",
                "availability": "in_stock",
            }
        ],
    }
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id="prod_expensive",
        merchant_domain="newegg.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=expensive_prod)

    assert evaluation.status == OrderStatus.BLOCKED
    assert any(v.rule == ViolationRule.BUDGET_EXCEEDED for v in evaluation.violations)


# ─────────────────────────────────────────────────────────────────────────────
# Test Rule 4: Verification Passed & Routing
# ─────────────────────────────────────────────────────────────────────────────

def test_rule_4_verified_ready_for_paypal(base_policy, mock_valid_product):
    """Compliant request passes all checks and reaches VERIFIED_READY_FOR_PAYPAL."""
    req = OrderIntentRequest(
        policy_id=base_policy.policy_id,
        product_id=mock_valid_product["id"],
        merchant_domain="staples.com",
        quantity=1,
    )
    evaluation = verify_order_intent(req, base_policy, product_data=mock_valid_product)

    assert evaluation.status == OrderStatus.VERIFIED_READY_FOR_PAYPAL
    assert len(evaluation.violations) == 0
    assert evaluation.computed_subtotal == "899.99"
    assert evaluation.remediation is None


# ─────────────────────────────────────────────────────────────────────────────
# Test Rate Limiter Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────

def test_rate_limiter_circuit_breaker():
    """Circuit breaker tracks daily API quotas and returns status."""
    status = daily_counter.get_status()
    assert "channel3_calls_today" in status
    assert "llm_calls_today" in status
    assert "channel3_daily_cap" in status
    assert "llm_daily_cap" in status

    # Verify increment within cap
    within_cap = daily_counter.increment_channel3()
    assert isinstance(within_cap, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Test FastAPI HTTP Endpoints
# ─────────────────────────────────────────────────────────────────────────────

client = TestClient(app)


def test_endpoint_health():
    """GET /api/health must return service status and integration configuration."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "ok", "degraded")
    assert "channel3_configured" in data
    assert "paypal_configured" in data


def test_endpoint_get_policy():
    """GET /api/policy returns the active spending policy."""
    res = client.get("/api/policy")
    assert res.status_code == 200
    data = res.json()
    assert data["currency"] == "USD"
    assert "auto_approve_under" in data


def test_endpoint_get_presets():
    """GET /api/presets returns attack arena presets."""
    res = client.get("/api/presets")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 4


def test_endpoint_get_fixtures():
    """GET /api/products/fixtures returns catalog items."""
    res = client.get("/api/products/fixtures")
    assert res.status_code == 200
    data = res.json()
    assert len(data) > 0


def test_endpoint_verify_and_pay_blocked_flow():
    """POST /api/verify-and-pay blocks spec spoof and returns structured remediation."""
    payload = {
        "policy_id": "laptop_spending_policy_01",
        "product_id": "0HQkNwE",  # Dell 8GB
        "merchant_domain": "bestbuy.com",
        "quantity": 1,
    }
    res = client.post("/api/verify-and-pay", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "evaluation" in data
    assert data["evaluation"]["status"] == "BLOCKED"
    assert len(data["evaluation"]["violations"]) > 0
    assert data["evaluation"]["remediation"] is not None
