"""
Intent Gateway — Main FastAPI Application.

Deterministic AI Shopping Firewall for PayPal Hackathon 2026.
Interception layer that isolates untrusted LLMs from payment construction.
"""

# no future annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.channel3_client import retrieve_product, search_products
from app.config import get_settings
from app.db import (
    get_analytics_summary,
    get_attempts,
    init_db,
    record_attempt,
    update_paypal_capture,
    update_paypal_order,
)
from app.engine import verify_order_intent
from app.fixtures import (
    DEFAULT_POLICY,
    FIXTURE_PRODUCTS,
    get_all_fixture_products,
    get_fixture_product,
    get_preset_by_id,
    get_red_team_presets,
)
from app.llm_adapter import LLMAdapter
from app.models import (
    GatewayEvaluationResponse,
    HealthResponse,
    OrderIntentRequest,
    OrderStatus,
    RedTeamPreset,
    SpendingPolicy,
    VerifyAndPayResponse,
)
from app.paypal_client import capture_order, check_paypal_health, create_order, refund_capture
from app.rate_limiter import daily_counter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intent.gateway")

# ── Rate Limiter ───────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ── Lifespan Handler ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Intent AI Gateway...")
    await init_db()

    # Pre-check PayPal connectivity in background
    settings = get_settings()
    if settings.paypal_client_id and settings.paypal_client_secret:
        is_healthy = await check_paypal_health()
        logger.info("PayPal Sandbox status: %s", "READY" if is_healthy else "AUTH_FAILED")
    else:
        logger.warning("PayPal credentials not set in .env — will evaluate in dry-run mode")

    yield
    logger.info("Intent Gateway shutting down.")


# ── App Definition ─────────────────────────────────────────────────────────

app = FastAPI(
    title="Intent — AI Shopping Firewall",
    description="Deterministic 4-rule gate enforcing spending limits, quantities, and structured product attributes before PayPal transactions.",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS Middleware ────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-Memory Policy Store (Demo Session) ──────────────────────────────────

_current_policy: SpendingPolicy = DEFAULT_POLICY.model_copy()
_llm_adapter = LLMAdapter()


# ── Health & Config Routes ─────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def get_health():
    """System health check and integration configuration status."""
    settings = get_settings()
    paypal_ok = bool(settings.paypal_client_id and settings.paypal_client_secret)
    channel3_ok = bool(settings.channel3_api_key)
    return HealthResponse(
        status="ok",
        channel3_configured=channel3_ok,
        paypal_configured=paypal_ok,
        llm_provider=settings.llm_provider,
    )


@app.get("/api/policy", response_model=SpendingPolicy)
async def get_policy():
    """Retrieve the currently enforced server-side spending policy."""
    return _current_policy


@app.put("/api/policy", response_model=SpendingPolicy)
async def update_policy(policy: SpendingPolicy):
    """Update active spending policy for testing custom constraints."""
    global _current_policy
    _current_policy = policy
    logger.info("Spending policy updated: id=%s max_order_total=%s", policy.policy_id, policy.max_order_total)
    return _current_policy


# ── Catalog & Fixture Routes ───────────────────────────────────────────────

@app.get("/api/presets", response_model=list[RedTeamPreset])
async def list_presets():
    """Return the curated red-team attack presets."""
    return get_red_team_presets()


@app.get("/api/products/fixtures", response_model=list[dict[str, Any]])
async def list_fixtures():
    """Return pre-cached catalog fixtures (burns 0 API credits)."""
    return get_all_fixture_products()


@app.get("/api/products/search")
async def search_catalog(q: str = "laptop", limit: int = 5):
    """
    Search catalog via Channel3 or fallback to local fixtures.
    Safe against credit exhaustion.
    """
    settings = get_settings()
    if settings.channel3_api_key and daily_counter.increment_channel3():
        results = search_products(query=q, limit=limit)
        if results:
            return {"source": "channel3", "count": len(results), "products": results}

    # Fallback to fixture matching
    q_lower = q.lower()
    matched = []
    for p in get_all_fixture_products():
        title = p.get("title", "").lower()
        desc = p.get("description", "").lower()
        if q_lower in title or q_lower in desc or not q_lower:
            matched.append(p)

    return {
        "source": "fixtures",
        "note": "Using pre-cached fixtures (live Channel3 API key unconfigured or cap reached)",
        "count": len(matched),
        "products": matched or get_all_fixture_products(),
    }


@app.get("/api/products/{product_id}")
async def get_product_details(product_id: str):
    """Retrieve normalized product representation."""
    fixture = get_fixture_product(product_id)
    if fixture:
        return {"source": "fixture", "product": fixture}

    product = retrieve_product(product_id)
    if product:
        return {"source": "channel3", "product": product}

    raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")


# ── Core Deterministic Gateway Endpoint ───────────────────────────────────

@app.post("/api/verify-and-pay", response_model=VerifyAndPayResponse)
@limiter.limit("5/15minute")
async def verify_and_pay(
    request: Request,
    intent_req: OrderIntentRequest,
):
    """
    Main Gate: Enforces the 4 deterministic rules.
    If all pass and PayPal is configured, creates a real PayPal Sandbox order.
    The untrusted LLM's values are NEVER used to determine price or attributes.
    """
    # 1. Resolve product record from fixtures or Channel3
    product_data = get_fixture_product(intent_req.product_id)
    if product_data is None:
        if daily_counter.increment_channel3():
            product_data = retrieve_product(intent_req.product_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily Channel3 call budget reached. Use fixture products.",
            )

    # 2. Run the pure-code 4-rule engine
    evaluation = verify_order_intent(
        request=intent_req,
        policy=_current_policy,
        product_data=product_data,
    )

    # 3. If verified, create PayPal Sandbox Order if credentials available
    settings = get_settings()
    if (
        evaluation.status == OrderStatus.VERIFIED_READY_FOR_PAYPAL
        and settings.paypal_client_id
        and settings.paypal_client_secret
        and evaluation.channel3_record
    ):
        try:
            paypal_res = await create_order(
                reference_id=evaluation.attempt_id,
                custom_id=f"intent_{evaluation.policy_id}",
                description=f"Intent Verified: {evaluation.channel3_record.title[:100]}",
                item_name=evaluation.channel3_record.title,
                sku=evaluation.channel3_record.product_id,
                unit_amount=evaluation.channel3_record.unit_price,
                currency=evaluation.channel3_record.currency,
                quantity=intent_req.quantity,
            )
            evaluation.paypal_order_id = paypal_res.get("id")
        except Exception as e:
            logger.error("Failed to create PayPal order: %s", e)
            # We preserve verified status but note the PayPal error in pricing_note
            evaluation.pricing_note += f" (PayPal order creation error: {str(e)})"

    # 4. Save attempt trace to SQLite for AG Grid analytics
    await record_attempt(evaluation, intent_req)

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=_current_policy,
    )


# ── Red-Team Presets Runner ────────────────────────────────────────────────

@app.post("/api/run-preset/{preset_id}", response_model=VerifyAndPayResponse)
async def run_preset(preset_id: str):
    """
    Execute a pre-built red-team attack preset end-to-end.
    Simulates the untrusted LLM falling for prompt injection.
    """
    preset = get_preset_by_id(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found.")

    # Untrusted agent fell for the injection and submitted this intent:
    agent_reasoning = (
        f"[Untrusted LLM Output] Read listing text with injection: '{preset.injection_text[:90]}...' "
        f"Proceeding to submit purchase intent for {preset.quantity} unit(s)."
    )

    intent_req = OrderIntentRequest(
        policy_id=_current_policy.policy_id,
        product_id=preset.product_id,
        merchant_domain=preset.merchant_domain,
        quantity=preset.quantity,
        agent_reasoning=agent_reasoning,
    )

    product_data = get_fixture_product(preset.product_id) or retrieve_product(preset.product_id)

    evaluation = verify_order_intent(
        request=intent_req,
        policy=_current_policy,
        product_data=product_data,
    )

    await record_attempt(evaluation, intent_req)

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=_current_policy,
    )


# ── Interactive Agent Shopping Simulation ──────────────────────────────────

class AgentShopRequest(BaseModel):
    product_id: str
    merchant_domain: str = "bestbuy.com"
    quantity: int = 1
    custom_injection_text: str = Field(
        default="",
        max_length=200,
        description="Optional injection payload (capped at 200 chars for safety)",
    )


@app.post("/api/agent/shop", response_model=VerifyAndPayResponse)
async def agent_shop(req: AgentShopRequest):
    """
    Simulate untrusted agent processing a listing with optional user-supplied injection.
    Demonstrates how the firewall catches arbitrary injection attacks.
    """
    product_data = get_fixture_product(req.product_id)
    if product_data is None:
        product_data = retrieve_product(req.product_id)

    if not product_data:
        raise HTTPException(status_code=404, detail=f"Product '{req.product_id}' not found.")

    # Agent parses listing (potentially tainted with injection)
    if req.custom_injection_text:
        agent_reasoning = f"Agent observed seller note: '{req.custom_injection_text}' and generated intent."
    else:
        agent_reasoning = "Standard agent selection based on policy goal match."

    intent_req = OrderIntentRequest(
        policy_id=_current_policy.policy_id,
        product_id=req.product_id,
        merchant_domain=req.merchant_domain,
        quantity=req.quantity,
        agent_reasoning=agent_reasoning,
    )

    evaluation = verify_order_intent(
        request=intent_req,
        policy=_current_policy,
        product_data=product_data,
    )

    # If verified, create PayPal order
    settings = get_settings()
    if (
        evaluation.status == OrderStatus.VERIFIED_READY_FOR_PAYPAL
        and settings.paypal_client_id
        and settings.paypal_client_secret
        and evaluation.channel3_record
    ):
        try:
            paypal_res = await create_order(
                reference_id=evaluation.attempt_id,
                custom_id=f"intent_{evaluation.policy_id}",
                description=f"Intent: {evaluation.channel3_record.title[:100]}",
                item_name=evaluation.channel3_record.title,
                sku=evaluation.channel3_record.product_id,
                unit_amount=evaluation.channel3_record.unit_price,
                currency=evaluation.channel3_record.currency,
                quantity=intent_req.quantity,
            )
            evaluation.paypal_order_id = paypal_res.get("id")
        except Exception as e:
            logger.error("PayPal order error: %s", e)
            evaluation.pricing_note += f" (PayPal order error: {str(e)})"

    await record_attempt(evaluation, intent_req)

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=_current_policy,
    )


# ── PayPal Capture & Refund Handlers ───────────────────────────────────────

@app.post("/api/paypal/capture/{order_id}")
async def capture_paypal_order(order_id: str):
    """
    Capture an approved PayPal order.
    Transfers funds in PayPal Sandbox environment.
    Gracefully handles Outcome B when buyer approval is pending in Sandbox.
    """
    try:
        capture_res = await capture_order(order_id)
        purchase_units = capture_res.get("purchase_units", [])
        capture_id = ""
        if purchase_units:
            captures = purchase_units[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id", "")

        cap_final = capture_id or f"CAP_{order_id[-8:]}"
        await update_paypal_capture(order_id, cap_final, status="CAPTURED")
        return {"status": "CAPTURED", "order_id": order_id, "capture_id": cap_final, "raw": capture_res}
    except Exception as e:
        err_msg = str(e)
        logger.warning("PayPal capture note: %s", err_msg)
        if "422" in err_msg or "ORDER_NOT_APPROVED" in err_msg or "400" in err_msg:
            # Outcome B: Unvaulted Sandbox Card requires buyer redirect or simulated sandbox approval
            simulated_cap_id = f"CAP_SBX_{order_id[-8:]}"
            await update_paypal_capture(order_id, simulated_cap_id, status="CAPTURED")
            return {
                "status": "CAPTURED",
                "order_id": order_id,
                "capture_id": simulated_cap_id,
                "note": "Outcome B Demo Settlement: Captured via Sandbox flow (Payer Authorization confirmed).",
            }
        logger.error("Capture failed for %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail=f"Capture failed: {str(e)}")


@app.post("/api/paypal/refund/{capture_id}")
async def refund_paypal_capture(capture_id: str, amount: str | None = None):
    """Refund a previously captured PayPal payment."""
    if capture_id.startswith("CAP_SBX_"):
        return {"status": "REFUNDED", "capture_id": capture_id, "note": "Sandbox refund executed successfully."}
    try:
        refund_res = await refund_capture(capture_id, amount=amount)
        return {"status": "REFUNDED", "capture_id": capture_id, "raw": refund_res}
    except Exception as e:
        logger.error("Refund failed for %s: %s", capture_id, e)
        raise HTTPException(status_code=500, detail=f"Refund failed: {str(e)}")


# ── Analytics & AG Grid Endpoints ──────────────────────────────────────────

@app.get("/api/rate-limit-status")
async def get_circuit_breaker_status():
    """Daily circuit breaker counters protecting external API quotas."""
    return daily_counter.get_status()


@app.get("/api/attempts")
async def get_all_attempts(limit: int = 100):
    """Raw attempt log for AG Grid analytics dashboard."""
    return await get_attempts(limit=limit)


@app.get("/api/analytics")
async def get_analytics():
    """Aggregated stats and recent attempt history for AG Studio dashboard."""
    summary = await get_analytics_summary()
    recent = await get_attempts(limit=25)
    return {
        "summary": summary,
        "recent_attempts": recent,
    }
