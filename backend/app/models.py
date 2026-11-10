"""Intent Gateway — Pydantic data models matching the PRD schemas."""

# no future annotations
from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────


class OrderStatus(str, Enum):
    BLOCKED = "BLOCKED"
    VERIFIED_READY_FOR_PAYPAL = "VERIFIED_READY_FOR_PAYPAL"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class ViolationRule(str, Enum):
    OFFER_UNAVAILABLE = "OFFER_UNAVAILABLE"
    STRUCTURED_ATTRIBUTE_MISMATCH = "STRUCTURED_ATTRIBUTE_MISMATCH"
    UNVERIFIABLE_ATTRIBUTE = "UNVERIFIABLE_ATTRIBUTE"
    MAX_QUANTITY_EXCEEDED = "MAX_QUANTITY_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    MANDATE_NOT_FOUND = "MANDATE_NOT_FOUND"
    MANDATE_EXPIRED = "MANDATE_EXPIRED"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MANDATE_SIGNATURE_INVALID = "MANDATE_SIGNATURE_INVALID"
    MANDATE_AGENT_MISMATCH = "MANDATE_AGENT_MISMATCH"
    DAILY_LIMIT_EXCEEDED = "DAILY_LIMIT_EXCEEDED"
    WEEKLY_LIMIT_EXCEEDED = "WEEKLY_LIMIT_EXCEEDED"
    MERCHANT_LIMIT_EXCEEDED = "MERCHANT_LIMIT_EXCEEDED"
    VELOCITY_LIMIT_EXCEEDED = "VELOCITY_LIMIT_EXCEEDED"
    PRICE_DRIFT = "PRICE_DRIFT"


class RemediationAction(str, Enum):
    SWITCH_PRODUCT = "SWITCH_PRODUCT"
    REDUCE_QUANTITY = "REDUCE_QUANTITY"
    SWITCH_PRODUCT_AND_SET_QUANTITY = "SWITCH_PRODUCT_AND_SET_QUANTITY"
    WAIT_OR_REDUCE = "WAIT_OR_REDUCE"
    RETRY_LATER = "RETRY_LATER"


# ── Spending Policy (Server-Side) ─────────────────────────────────────────


class SpendingPolicy(BaseModel):
    """Server-side spending policy. The LLM never sees this directly."""

    policy_id: str = Field(..., description="Unique policy identifier")
    search_goal: str = Field(..., description="Human-readable search goal")
    currency: str = Field(default="USD")
    max_order_total: str = Field(..., description="Max order total as decimal string")
    auto_approve_under: str = Field(..., description="Auto-approve threshold as decimal string")
    max_quantity: int = Field(..., ge=1, description="Max units per order")
    required_availability: str = Field(default="InStock")
    required_structured_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Keys must be canonical Channel3 structured_attributes handles",
    )


# ── Untrusted Agent Submission ─────────────────────────────────────────────


class OrderIntentRequest(BaseModel):
    """What the shopping LLM submits — references only, no prices or specs."""

    mandate_id: Optional[str] = None
    policy_id: Optional[str] = None
    product_id: str
    merchant_domain: str
    quantity: int = Field(..., ge=1)
    agent_reasoning: str = Field(
        default="",
        max_length=500,
        description="The LLM's stated reasoning (logged but never trusted)",
    )

    def model_post_init(self, __context) -> None:
        if not self.mandate_id and self.policy_id:
            self.mandate_id = self.policy_id
        elif not self.policy_id and self.mandate_id:
            self.policy_id = self.mandate_id


# ── Channel3 Product Data (Gateway-Pulled) ─────────────────────────────────


class Channel3Offer(BaseModel):
    """A single merchant offer from Channel3 product.offers[]."""

    domain: str
    url: str = ""
    price: str  # Decimal string, e.g. "799.00"
    currency: str = "USD"
    availability: str = ""
    condition: str = ""


class Channel3Record(BaseModel):
    """Normalized product record pulled server-side from Channel3."""

    product_id: str
    title: str
    merchant_domain: str
    availability: str
    unit_price: str
    currency: str = "USD"
    structured_attributes: dict[str, str] = Field(default_factory=dict)
    image_url: str = ""
    description: str = ""


# ── Gateway Evaluation ─────────────────────────────────────────────────────


class Violation(BaseModel):
    rule: ViolationRule
    detail: str


class Remediation(BaseModel):
    action: RemediationAction
    allowed_quantity: int | None = None
    exclude_product_ids: list[str] = Field(default_factory=list)
    instruction: str = ""
    remaining_headroom: Optional[str] = None


class GatewayEvaluationResponse(BaseModel):
    """The deterministic gateway's evaluation result."""

    attempt_id: str
    policy_id: str
    mandate_id: Optional[str] = None
    status: OrderStatus
    channel3_record: Channel3Record | None = None
    computed_subtotal: str | None = None
    pricing_note: str = "Catalog offer price only; tax and shipping excluded in sandbox."
    violations: list[Violation] = Field(default_factory=list)
    remediation: Remediation | None = None

    # PayPal fields (populated when status is CAPTURED or VERIFIED_READY_FOR_PAYPAL)
    paypal_order_id: str | None = None
    paypal_capture_id: str | None = None

    def model_post_init(self, __context) -> None:
        if not self.mandate_id and self.policy_id:
            self.mandate_id = self.policy_id


# ── Red-Team Preset ────────────────────────────────────────────────────────


class RedTeamPreset(BaseModel):
    """A pre-built red-team attack scenario for the demo UI."""

    preset_id: str
    name: str
    description: str
    injection_text: str = Field(max_length=200)
    expected_violations: list[ViolationRule]
    product_id: str
    merchant_domain: str
    quantity: int = 1


# ── API Response Wrappers ──────────────────────────────────────────────────


class VerifyAndPayResponse(BaseModel):
    """Top-level response from POST /api/verify-and-pay."""

    evaluation: GatewayEvaluationResponse
    agent_request: OrderIntentRequest
    policy: Optional[SpendingPolicy] = None
    mandate: Optional[Any] = None
    approval_id: Optional[str] = None
    needs_human_approval: bool = False
    approval_token: Optional[str] = None
    escalation_reason: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    channel3_configured: bool = False
    paypal_configured: bool = False
    llm_provider: str = "stub"
    app_mode: str = "demo"
    app_env: str = "development"
    key_source: str = "generated"  # "env" | "generated"
    database_type: str = "sqlite"  # "sqlite" | "postgresql"
    persistent_storage: bool = True
    worker_count: int = 1


# Rebuild models to resolve forward references with Pydantic v2
Channel3Record.model_rebuild()
GatewayEvaluationResponse.model_rebuild()
VerifyAndPayResponse.model_rebuild()

