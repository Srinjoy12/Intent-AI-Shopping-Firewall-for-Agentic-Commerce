"""
Intent Gateway — The 4-Rule Deterministic Verification Engine.

This is the core trust boundary. When POST /api/verify-and-pay receives an
OrderIntentRequest, it calls client.products.retrieve(req.product_id) and
runs four pure-code checks. The untrusted LLM never touches any of these
values — it can only submit { policy_id, product_id, merchant_domain, quantity }.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from app.models import (
    Channel3Record,
    GatewayEvaluationResponse,
    OrderIntentRequest,
    OrderStatus,
    Remediation,
    RemediationAction,
    SpendingPolicy,
    Violation,
    ViolationRule,
)
from app.channel3_client import (
    retrieve_product,
    find_offer_by_domain,
    build_channel3_record,
)

logger = logging.getLogger(__name__)


def _generate_attempt_id() -> str:
    return f"att_{uuid.uuid4().hex[:8]}"


def verify_order_intent(
    request: OrderIntentRequest,
    policy: SpendingPolicy | Any,
    product_data: dict | None = None,
) -> GatewayEvaluationResponse:
    """
    Run all 4 deterministic rules against the agent's order intent.

    Args:
        request: The untrusted LLM submission (product_id, domain, quantity only).
        policy: The verified signed mandate or spending policy with budget and attribute limits.
        product_data: Optional pre-fetched product data (for cached/fixture products).
                      If None, we call Channel3 retrieve().

    Returns:
        GatewayEvaluationResponse with BLOCKED or VERIFIED_READY_FOR_PAYPAL status.
    """
    attempt_id = _generate_attempt_id()
    effective_policy_id = getattr(policy, "mandate_id", getattr(policy, "policy_id", request.mandate_id or request.policy_id or ""))
    violations: list[Violation] = []

    # ── Step 0: Retrieve product from Channel3 (server-to-server) ──────────

    if product_data is None:
        product_data = retrieve_product(request.product_id)

    if product_data is None:
        return GatewayEvaluationResponse(
            attempt_id=attempt_id,
            policy_id=effective_policy_id,
            mandate_id=effective_policy_id,
            status=OrderStatus.BLOCKED,
            violations=[
                Violation(
                    rule=ViolationRule.OFFER_UNAVAILABLE,
                    detail=f"Product {request.product_id} not found in Channel3 catalog.",
                )
            ],
            remediation=Remediation(
                action=RemediationAction.SWITCH_PRODUCT,
                exclude_product_ids=[request.product_id],
                instruction=f"Product {request.product_id} not found. Select a different product_id.",
            ),
        )

    # ── Rule 1: Offer Domain & Availability ────────────────────────────────

    allowed_domains = getattr(policy, "allowed_domains", None)
    if allowed_domains is None:
        allowed_domains = getattr(policy, "allowed_merchant_domains", None)

    if allowed_domains and request.merchant_domain not in allowed_domains:
        violations.append(
            Violation(
                rule=ViolationRule.OFFER_UNAVAILABLE,
                detail=(
                    f"Merchant domain '{request.merchant_domain}' is not in "
                    f"authorized domains list: {allowed_domains}."
                ),
            )
        )

    offer = find_offer_by_domain(product_data, request.merchant_domain)

    if offer is None:
        # Avoid duplicate violation if already flagged for not in allowed_domains
        if not any(v.rule == ViolationRule.OFFER_UNAVAILABLE for v in violations):
            violations.append(
                Violation(
                    rule=ViolationRule.OFFER_UNAVAILABLE,
                    detail=(
                        f"No offer found for domain '{request.merchant_domain}' "
                        f"in product {request.product_id}."
                    ),
                )
            )
    elif offer.get("availability", "").lower() != policy.required_availability.lower():
        violations.append(
            Violation(
                rule=ViolationRule.OFFER_UNAVAILABLE,
                detail=(
                    f"Offer from {request.merchant_domain} has availability "
                    f"'{offer.get('availability', 'unknown')}'; "
                    f"policy requires '{policy.required_availability}'."
                ),
            )
        )

    # Build Channel3 record for the response (even if Rule 1 failed)
    channel3_record = None
    unit_price_str = "0"
    if offer is not None:
        channel3_record = build_channel3_record(
            product_data, offer, request.merchant_domain
        )
        unit_price_str = offer.get("price", "0")
    else:
        # Use first offer if available, for informational display
        all_offers = product_data.get("offers", [])
        if all_offers:
            channel3_record = build_channel3_record(
                product_data, all_offers[0], request.merchant_domain
            )
            unit_price_str = all_offers[0].get("price", "0")

    # ── Rule 2: Structured Attributes Only (Fail-Closed) ───────────────────

    product_attrs = product_data.get("structured_attributes", {}) or {}
    req_attrs = getattr(policy, "required_attributes", None)
    if req_attrs is None:
        req_attrs = getattr(policy, "required_structured_attributes", {}) or {}

    for attr_key, required_value in req_attrs.items():
        actual_value = product_attrs.get(attr_key)

        if actual_value is None:
            # Key missing from Channel3 structured_attributes → fail closed
            violations.append(
                Violation(
                    rule=ViolationRule.UNVERIFIABLE_ATTRIBUTE,
                    detail=(
                        f"Channel3 structured_attributes has no key '{attr_key}'. "
                        f"Policy requires '{attr_key}' = '{required_value}'. "
                        f"Cannot verify — fail closed."
                    ),
                )
            )
        else:
            # Normalize whitespace and casing for robust comparison (e.g. '16 GB' == '16GB')
            norm_actual = str(actual_value).lower().replace(" ", "")
            norm_required = str(required_value).lower().replace(" ", "")

            # Check exact compact match or membership in multi-valued attribute
            multi_vals = [v.strip().replace(" ", "") for v in str(actual_value).lower().split(",")]
            if norm_actual != norm_required and norm_required not in multi_vals:
                violations.append(
                    Violation(
                        rule=ViolationRule.STRUCTURED_ATTRIBUTE_MISMATCH,
                        detail=(
                            f"Channel3 structured_attributes['{attr_key}'] is '{actual_value}'; "
                            f"policy requires '{required_value}'."
                        ),
                    )
                )

    # ── Rule 3: Quantity & Offer Price Math ────────────────────────────────

    if request.quantity > policy.max_quantity:
        violations.append(
            Violation(
                rule=ViolationRule.MAX_QUANTITY_EXCEEDED,
                detail=(
                    f"Requested quantity ({request.quantity}) exceeds "
                    f"policy max_quantity ({policy.max_quantity})."
                ),
            )
        )

    # Compute subtotal
    try:
        unit_price = Decimal(unit_price_str)
    except (InvalidOperation, ValueError):
        unit_price = Decimal("0")

    computed_subtotal = unit_price * request.quantity

    try:
        max_total = Decimal(policy.max_order_total)
    except (InvalidOperation, ValueError):
        max_total = Decimal("0")

    if computed_subtotal > max_total:
        violations.append(
            Violation(
                rule=ViolationRule.BUDGET_EXCEEDED,
                detail=(
                    f"Computed subtotal (${computed_subtotal:.2f}) exceeds "
                    f"policy max_order_total (${max_total:.2f})."
                ),
            )
        )

    # ── Determine Status & Remediation ─────────────────────────────────────

    if violations:
        # Build remediation instruction
        has_attr_issue = any(
            v.rule in (ViolationRule.STRUCTURED_ATTRIBUTE_MISMATCH, ViolationRule.UNVERIFIABLE_ATTRIBUTE)
            for v in violations
        )
        has_qty_issue = any(v.rule == ViolationRule.MAX_QUANTITY_EXCEEDED for v in violations)

        if has_attr_issue and has_qty_issue:
            action = RemediationAction.SWITCH_PRODUCT_AND_SET_QUANTITY
            instruction = (
                f"Product {request.product_id} fails structured attribute check. "
                f"Select another product_id where structured_attributes meets policy "
                f"and set quantity to {policy.max_quantity}."
            )
        elif has_attr_issue:
            action = RemediationAction.SWITCH_PRODUCT
            instruction = (
                f"Product {request.product_id} fails structured attribute check. "
                f"Select another product_id where structured_attributes meets policy."
            )
        elif has_qty_issue:
            action = RemediationAction.REDUCE_QUANTITY
            instruction = f"Reduce quantity to at most {policy.max_quantity}."
        else:
            action = RemediationAction.SWITCH_PRODUCT
            instruction = "Select a different product or merchant domain."

        return GatewayEvaluationResponse(
            attempt_id=attempt_id,
            policy_id=effective_policy_id,
            mandate_id=effective_policy_id,
            status=OrderStatus.BLOCKED,
            channel3_record=channel3_record,
            computed_subtotal=f"{computed_subtotal:.2f}",
            violations=violations,
            remediation=Remediation(
                action=action,
                allowed_quantity=min(request.quantity, policy.max_quantity),
                exclude_product_ids=[request.product_id] if has_attr_issue else [],
                instruction=instruction,
            ),
        )

    # ── Rule 4: PayPal Execution Routing ───────────────────────────────────
    # All checks passed. The order is verified and ready for PayPal.
    # The actual PayPal order creation happens in the API route,
    # which checks auto_approve_under for routing.

    return GatewayEvaluationResponse(
        attempt_id=attempt_id,
        policy_id=effective_policy_id,
        mandate_id=effective_policy_id,
        status=OrderStatus.VERIFIED_READY_FOR_PAYPAL,
        channel3_record=channel3_record,
        computed_subtotal=f"{computed_subtotal:.2f}",
        violations=[],
        remediation=None,
    )
