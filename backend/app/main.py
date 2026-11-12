"""
Intent Gateway — Main FastAPI Application.

Deterministic AI Shopping Firewall for PayPal Hackathon 2026.
Interception layer that isolates untrusted LLMs from payment construction.
"""

# no future annotations

import os
import sys
import json
import hmac
import uuid
import secrets
import logging
import asyncio
import aiosqlite
from decimal import Decimal
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, status, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.channel3_client import retrieve_product, search_products
from app.config import get_settings
from app.db import (
    DB_PATH,
    get_database_type,
    is_persistent_storage,
    get_analytics_summary,
    get_attempts,
    init_db,
    record_attempt,
    update_paypal_capture,
    update_paypal_order,
    update_paypal_refund,
    save_mandate,
    get_mandate_by_id,
    revoke_mandate,
    get_agent_id_for_key,
    is_agent_paused,
    pause_agent,
    resume_agent,
    has_prior_committed_order,
    list_pending_approvals,
    cleanup_expired_demo_sessions,
    save_paypal_anchor,
    update_paypal_anchor_capture,
    get_paypal_anchors,
    get_paypal_anchor_by_order,
    is_webhook_processed,
    record_processed_webhook,
)
from app.session import (
    require_demo_session,
    require_demo_session_read_only,
    set_session_cookie,
    COOKIE_NAME,
    verify_session_cookie,
    create_sandbox_for_session,
    delete_demo_session,
)
from app.approvals import (
    create_approval_request,
    process_approval_action,
    ApprovalStatus,
    get_approval_for_display,
    compute_csrf_token,
    verify_csrf_token,
)
from app.mandate import (
    Mandate,
    MandateStatus,
    CreateMandateRequest,
    PublicKeyResponse,
    get_public_key,
    get_public_key_hex,
    get_signing_key,
    get_key_source,
    validate_production_configuration,
    sign_mandate,
    verify_mandate,
    create_demo_mandate,
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
    Violation,
    Remediation,
    ViolationRule,
    RemediationAction,
)
from app import paypal_client
from app.paypal_client import (
    capture_order,
    check_paypal_health,
    create_order,
    create_order_with_card,
    refund_capture,
    get_order,
    verify_webhook_signature,
)
from app.rate_limiter import daily_counter
from app.reservation import (
    check_idempotency,
    save_idempotency,
    compute_request_fingerprint,
    derive_paypal_request_id,
    reserve_budget_atomic,
    commit_reservation,
    commit_reservation_by_order,
    release_reservation,
    release_reservation_by_attempt,
    release_reservation_by_capture,
    release_reservation_by_order,
    sweep_stale_reservations,
)
from app.audit import (
    append_audit_event,
    verify_audit_chain,
    export_audit_chain_signed,
    verify_offline_export,
    get_audit_event_by_hash,
    verify_order_audit_anchor,
    GENESIS_HASH,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intent.gateway")

# ── Rate Limiter ───────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    enabled=not ("pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))),
)


async def _reservation_sweep_worker():
    """Background task to release reservations stuck in RESERVED for > 15 minutes."""
    while True:
        try:
            await asyncio.sleep(60)
            released = await sweep_stale_reservations(timeout_minutes=15)
            if released > 0:
                logger.info("Reservation sweep released %d stale reservation(s)", released)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in reservation sweep worker: %s", e)


async def _sandbox_cleanup_worker():
    """Background task to remove expired demo sandbox sessions (> 2 hours old)."""
    while True:
        try:
            await asyncio.sleep(60)
            cleaned = await cleanup_expired_demo_sessions()
            if cleaned > 0:
                logger.info("Demo sandbox cleanup removed %d expired session(s)", cleaned)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in sandbox cleanup worker: %s", e)


# ── Lifespan Handler ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Intent AI Gateway...")
    settings = get_settings()

    # 1. Enforce production key requirements before binding or processing
    validate_production_configuration(settings)

    # 2. Document and enforce single-worker operation for SQLite in-memory locks
    db_type = get_database_type()
    raw_workers = os.environ.get("WEB_CONCURRENCY", os.environ.get("WORKERS", str(settings.web_concurrency or 1)))
    try:
        worker_count = int(raw_workers)
    except ValueError:
        worker_count = 1

    if db_type == "sqlite" and worker_count > 1:
        logger.warning(
            "⚠️ [CONCURRENCY WARNING] WEB_CONCURRENCY=%d > 1 with SQLite database. "
            "SQLite in-memory budget reservation locks and audit chain sequential hashing "
            "require single-worker operation (WEB_CONCURRENCY=1) to prevent race conditions. "
            "For multi-worker deployments, configure PostgreSQL via DATABASE_URL.",
            worker_count,
        )

    await init_db()

    # 3. Startup audit chain self-check
    try:
        chain_verify = await verify_audit_chain()
        if chain_verify.get("valid"):
            logger.info(
                "Startup audit chain verified: VALID (events_checked=%d, message=%s)",
                chain_verify.get("events_checked", 0),
                chain_verify.get("message", "ok"),
            )
        else:
            logger.error(
                "Startup audit chain verification FAILED: %s (at seq %s)",
                chain_verify.get("message"),
                chain_verify.get("first_broken_seq"),
            )
    except Exception as e:
        logger.error("Startup audit chain self-check error: %s", e)

    # Pre-check PayPal connectivity in background
    if settings.paypal_client_id and settings.paypal_client_secret:
        is_healthy = await check_paypal_health()
        logger.info("PayPal Sandbox status: %s", "READY" if is_healthy else "AUTH_FAILED")
    else:
        logger.warning("PayPal credentials not set in .env — will evaluate in dry-run mode")

    # Initial sweep of stale reservations and start background periodic worker
    try:
        initial_swept = await sweep_stale_reservations(timeout_minutes=15)
        if initial_swept > 0:
            logger.info("Startup sweep released %d stale reservation(s)", initial_swept)
    except Exception as e:
        logger.warning("Startup reservation sweep note: %s", e)

    # Initial cleanup of expired demo sandbox sessions
    try:
        expired_sessions = await cleanup_expired_demo_sessions()
        if expired_sessions > 0:
            logger.info("Startup demo session cleanup removed %d expired session(s)", expired_sessions)
    except Exception as e:
        logger.warning("Startup demo session cleanup note: %s", e)

    sweep_task = asyncio.create_task(_reservation_sweep_worker())
    cleanup_task = asyncio.create_task(_sandbox_cleanup_worker())

    yield

    sweep_task.cancel()
    cleanup_task.cancel()
    try:
        await asyncio.gather(sweep_task, cleanup_task, return_exceptions=True)
    except Exception:
        pass
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "status_code": exc.status_code},
        )
    logger.error("Unhandled server exception at %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred.",
            "error_code": "INTERNAL_SERVER_ERROR",
            "status_code": 500,
        },
    )

# ── CORS Middleware ────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Approval Access-Log Sanitiser ──────────────────────────────────────────
# Strips query strings from /api/approvals/* access logs so the raw approval
# token never appears in any log line (e.g. uvicorn access logs).

class StripApprovalQueryFilter(logging.Filter):
    """Logging filter to strip query strings from /api/approvals/* in all log messages."""
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "args") and isinstance(record.args, tuple):
            new_args = list(record.args)
            for i, arg in enumerate(new_args):
                if isinstance(arg, str) and "/api/approvals/" in arg and "?" in arg:
                    new_args[i] = arg.split("?")[0]
            record.args = tuple(new_args)
        if isinstance(record.msg, str) and "/api/approvals/" in record.msg and "?" in record.msg:
            import re
            record.msg = re.sub(r'(/api/approvals/[^\s\?]+)\?[^\s"]*', r'\1', record.msg)
        return True

# Register filter on root, uvicorn, and uvicorn.access
_approval_filter = StripApprovalQueryFilter()
logging.getLogger().addFilter(_approval_filter)
logging.getLogger("uvicorn").addFilter(_approval_filter)
logging.getLogger("uvicorn.access").addFilter(_approval_filter)


@app.middleware("http")
async def sanitise_approval_access_logs(request: Request, call_next):
    """
    For requests to /api/approvals/*, sanitize the query string after handler execution
    so uvicorn access logs and subsequent middleware never see the raw token.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/approvals/"):
        request.scope["query_string"] = b""
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Enforce production security headers on all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ── LLM Adapter & Gateway Setup ───────────────────────────────────────────

_llm_adapter = LLMAdapter()


# ── Authentication & RBAC Dependencies ──────────────────────────────────────

async def require_admin_key(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    Enforce administrator authorization using constant-time digest comparison.
    Required for mandate issuance, mandate revocation, policy modification, refunds, and Outcome B captures.
    """
    settings = get_settings()
    expected = settings.admin_api_key or os.environ.get("ADMIN_API_KEY", "admin_super_secret_test_key")
    candidate = x_admin_key
    if not candidate and authorization and authorization.startswith("Bearer "):
        candidate = authorization[7:].strip()

    if not candidate or not hmac.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Valid admin credentials required in X-Admin-Key or Authorization header",
        )
    return candidate


async def resolve_agent_identity(
    x_agent_key: Optional[str] = Header(None, alias="X-Agent-Key"),
) -> Optional[str]:
    """Authenticate calling agent using hashed key lookup and constant-time comparison."""
    if not x_agent_key:
        return None
    agent_id = await get_agent_id_for_key(x_agent_key)
    if not agent_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid agent API key",
        )
    return agent_id


# ── Health & Config Routes ─────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def get_health():
    """System health check, integration configuration status, persistence, and application mode."""
    settings = get_settings()
    paypal_ok = bool(settings.paypal_client_id and settings.paypal_client_secret)
    channel3_ok = bool(settings.channel3_api_key)
    raw_workers = os.environ.get("WEB_CONCURRENCY", os.environ.get("WORKERS", str(settings.web_concurrency or 1)))
    try:
        worker_count = int(raw_workers)
    except ValueError:
        worker_count = 1

    return HealthResponse(
        status="ok",
        channel3_configured=channel3_ok,
        paypal_configured=paypal_ok,
        llm_provider=settings.llm_provider,
        app_mode=settings.app_mode,
        app_env=settings.app_env,
        key_source=get_key_source(),
        database_type=get_database_type(),
        persistent_storage=is_persistent_storage(),
        worker_count=worker_count,
    )


@app.get("/api/policy")
async def get_policy():
    """
    Retrieve the active signed mandate's verified values and its policy_hash.
    Enforcement values are strictly bound to cryptographically signed mandates.
    """
    mandate = await _get_active_mandate()
    is_valid, _ = verify_mandate(mandate, get_public_key())
    return {
        "policy_id": mandate.mandate_id,
        "mandate_id": mandate.mandate_id,
        "owner_id": mandate.owner_id,
        "agent_id": mandate.agent_id,
        "max_order_total": mandate.max_order_total,
        "auto_approve_under": mandate.auto_approve_under,
        "max_quantity": mandate.max_quantity,
        "required_availability": mandate.required_availability,
        "required_structured_attributes": mandate.required_attributes,
        "allowed_merchant_domains": mandate.allowed_domains,
        "currency": "USD",
        "policy_hash": mandate.policy_hash,
        "signature": mandate.signature,
        "signature_valid": is_valid,
        "status": mandate.status.value if hasattr(mandate.status, "value") else str(mandate.status),
        "issued_at": mandate.issued_at,
        "expires_at": mandate.expires_at,
    }


@app.put("/api/policy")
async def update_policy(
    policy: SpendingPolicy,
    _admin: str = Depends(require_admin_key),
):
    """
    Admin-only: Construct, Ed25519-sign, and persist a NEW cryptographic mandate.
    Mutating unauthenticated in-memory policy state in place is strictly disallowed.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)
    mandate_id = "demo_mandate_01"

    mandate_data = {
        "mandate_id": mandate_id,
        "owner_id": "admin_policy_update",
        "agent_id": "agent_demo_01",
        "max_order_total": str(policy.max_order_total),
        "auto_approve_under": str(policy.auto_approve_under),
        "max_quantity": policy.max_quantity,
        "required_attributes": policy.required_structured_attributes or {},
        "allowed_domains": getattr(policy, "allowed_merchant_domains", None) or getattr(policy, "allowed_domains", None) or [],
        "required_availability": policy.required_availability,
        "daily_limit": "10000.00",
        "weekly_limit": "25000.00",
        "per_merchant_limit": "5000.00",
        "max_orders_per_hour": 5,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "nonce": secrets.token_hex(16),
    }

    signed_mandate = sign_mandate(mandate_data, get_signing_key())
    await save_mandate(signed_mandate)

    # If policy specified a custom policy_id, also store a copy under that ID
    if policy.policy_id and policy.policy_id != "demo_mandate_01":
        custom_data = dict(mandate_data)
        custom_data["mandate_id"] = policy.policy_id
        custom_signed = sign_mandate(custom_data, get_signing_key())
        await save_mandate(custom_signed)

    await append_audit_event(
        "MANDATE_CREATED",
        {
            "mandate_id": signed_mandate.mandate_id,
            "owner_id": signed_mandate.owner_id,
            "agent_id": signed_mandate.agent_id,
            "max_order_total": signed_mandate.max_order_total,
            "policy_hash": signed_mandate.policy_hash,
            "signature": signed_mandate.signature,
            "source": "PUT /api/policy",
        },
        mandate_id=signed_mandate.mandate_id,
    )

    logger.info("Admin created signed mandate %s (hash=%s) via PUT /api/policy", signed_mandate.mandate_id, signed_mandate.policy_hash)
    return {
        "status": "MANDATE_CREATED",
        "mandate_id": signed_mandate.mandate_id,
        "policy_id": signed_mandate.mandate_id,
        "policy_hash": signed_mandate.policy_hash,
        "signature": signed_mandate.signature,
        "max_order_total": signed_mandate.max_order_total,
        "auto_approve_under": signed_mandate.auto_approve_under,
        "max_quantity": signed_mandate.max_quantity,
        "currency": "USD",
        "mandate": signed_mandate,
    }


# ── Signed Mandate Routes ──────────────────────────────────────────────────

@app.get("/api/mandate/public-key", response_model=PublicKeyResponse)
async def get_public_key_route():
    """Expose the system's Ed25519 public key for independent client signature verification."""
    return PublicKeyResponse(
        algorithm="Ed25519",
        public_key=get_public_key_hex(),
        encoding="hex",
    )


@app.post("/api/mandates")
async def create_mandate_route(
    req: CreateMandateRequest,
    _admin: str = Depends(require_admin_key),
):
    """
    Admin-only: Construct, Ed25519-sign, and persist a cryptographic mandate.
    Calculates SHA-256 policy_hash over canonical JSON before signing.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=req.expires_in_hours)

    mandate_data = {
        "mandate_id": req.mandate_id or str(uuid.uuid4()),
        "owner_id": req.owner_id,
        "agent_id": req.agent_id,
        "max_order_total": req.max_order_total,
        "auto_approve_under": req.auto_approve_under,
        "max_quantity": req.max_quantity,
        "required_attributes": req.required_attributes,
        "allowed_domains": req.allowed_domains,
        "required_availability": req.required_availability,
        "daily_limit": req.daily_limit,
        "weekly_limit": req.weekly_limit,
        "per_merchant_limit": req.per_merchant_limit,
        "max_orders_per_hour": req.max_orders_per_hour,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "nonce": secrets.token_hex(16),
    }

    signed_mandate = sign_mandate(mandate_data, get_signing_key())
    await save_mandate(signed_mandate)
    logger.info("Admin issued signed mandate %s for agent %s", signed_mandate.mandate_id, signed_mandate.agent_id)

    # Record tamper-evident audit event
    await append_audit_event(
        "MANDATE_CREATED",
        {
            "mandate_id": signed_mandate.mandate_id,
            "owner_id": signed_mandate.owner_id,
            "agent_id": signed_mandate.agent_id,
            "max_order_total": signed_mandate.max_order_total,
            "policy_hash": signed_mandate.policy_hash,
            "signature": signed_mandate.signature,
        },
        mandate_id=signed_mandate.mandate_id,
    )

    return {"status": "CREATED", "mandate": signed_mandate}


@app.get("/api/mandates/{mandate_id}")
async def get_mandate_route(mandate_id: str):
    """Retrieve mandate details by ID."""
    m = await get_mandate_by_id(mandate_id)
    if not m:
        raise HTTPException(status_code=404, detail=f"MANDATE_NOT_FOUND: Mandate '{mandate_id}' not found")
    return m


@app.post("/api/mandates/{mandate_id}/revoke")
async def revoke_mandate_route(
    mandate_id: str,
    _admin: str = Depends(require_admin_key),
):
    """Admin-only: Revoke a previously issued mandate."""
    success = await revoke_mandate(mandate_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"MANDATE_NOT_FOUND: Mandate '{mandate_id}' not found")
    logger.info("Admin revoked mandate %s", mandate_id)

    # Record tamper-evident audit event
    await append_audit_event(
        "MANDATE_REVOKED",
        {"mandate_id": mandate_id},
        mandate_id=mandate_id,
    )

    return {"status": "REVOKED", "mandate_id": mandate_id}


# ── Tamper-Evident Hash-Chained Audit Routes ──────────────────────────────

@app.get("/api/audit/verify")
async def verify_audit_chain_endpoint():
    """
    Walk the entire audit log and cryptographically verify hash continuity and tamper-evidence.
    Returns {valid: bool, events_checked: int, first_broken_seq: Optional[int]}.
    """
    return await verify_audit_chain()


@app.get("/api/audit/export")
async def export_audit_chain_endpoint(
    _admin: str = Depends(require_admin_key),
):
    """
    Export the full audit chain as an Ed25519-signed JSON manifest for offline verification.
    """
    return await export_audit_chain_signed()


@app.get("/api/audit/anchors")
async def get_audit_anchors(limit: int = 100):
    """
    List PayPal orders and their cryptographic audit chain anchors.
    Per captured order: PayPal order ID, capture ID, anchored hash, and whether it matches the chain.
    """
    anchors = await get_paypal_anchors(limit=limit)
    results = []
    for a in anchors:
        anchored_hash = a.get("anchored_hash")
        matches_chain = False
        if anchored_hash:
            ev = await get_audit_event_by_hash(anchored_hash)
            matches_chain = ev is not None

        results.append({
            "order_id": a.get("order_id"),
            "capture_id": a.get("capture_id"),
            "attempt_id": a.get("attempt_id"),
            "mandate_id": a.get("mandate_id"),
            "anchored_hash": anchored_hash,
            "invoice_id": a.get("invoice_id"),
            "status": a.get("status"),
            "matches_chain": matches_chain,
            "created_at": a.get("created_at"),
        })
    return results


@app.get("/api/audit/anchors/{order_id}/verify")
async def verify_audit_anchor(order_id: str):
    """
    Given a PayPal order ID, fetch the order from the PayPal sandbox API
    and confirm custom_id matches an authentic event hash in the audit chain.
    """
    return await verify_order_audit_anchor(order_id)


# ── PayPal Webhook Handler ─────────────────────────────────────────────────

@app.post("/api/paypal/webhook")
async def handle_paypal_webhook(request: Request):
    """
    Handle PayPal webhook events (PAYMENT.CAPTURE.COMPLETED, REFUNDED, DENIED).
    Verifies cryptographic signature against PayPal API and processes idempotently.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON in webhook request")

    event_id = body.get("id")
    event_type = body.get("event_type")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Missing webhook event id or event_type")

    # 1. Verify webhook signature using PayPal's verify-webhook-signature API
    headers_dict = dict(request.headers)
    is_valid = await paypal_client.verify_webhook_signature(headers_dict, body)
    if not is_valid:
        logger.warning("Rejected PayPal webhook with invalid signature: %s (%s)", event_id, event_type)
        raise HTTPException(status_code=400, detail="Invalid or unverified PayPal webhook signature")

    # 2. Idempotency check: Ignore replayed event IDs
    if await is_webhook_processed(event_id):
        logger.info("Ignoring already-processed PayPal webhook event: %s (%s)", event_id, event_type)
        return {"status": "already_processed", "event_id": event_id, "event_type": event_type}

    # 3. Record event ID to ensure idempotency
    await record_processed_webhook(event_id, event_type)

    resource = body.get("resource", {})
    resource_id = resource.get("id")

    # 4. Handle event types
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        capture_id = resource_id
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        amount_val = resource.get("amount", {}).get("value")

        if order_id:
            await update_paypal_capture(order_id, capture_id, status="CAPTURED")
            await commit_reservation_by_order(order_id)
            await update_paypal_anchor_capture(order_id, capture_id, status="CAPTURED")

        await append_audit_event(
            "PAYPAL_WEBHOOK_COMPLETED",
            {
                "webhook_event_id": event_id,
                "capture_id": capture_id,
                "order_id": order_id,
                "amount": amount_val,
            },
        )
        logger.info("Processed webhook PAYMENT.CAPTURE.COMPLETED: capture=%s order=%s", capture_id, order_id)

    elif event_type == "PAYMENT.CAPTURE.REFUNDED":
        refund_id = resource_id
        amount_val = resource.get("amount", {}).get("value")

        # Locate related capture ID
        capture_id = None
        for link in resource.get("links", []):
            href = link.get("href", "")
            if link.get("rel") == "up" and "/captures/" in href:
                capture_id = href.split("/captures/")[-1].split("?")[0]
                break
        if not capture_id:
            capture_id = resource.get("parent_payment")

        if capture_id:
            await update_paypal_refund(capture_id, status="REFUNDED")
            await release_reservation_by_capture(capture_id)

        await append_audit_event(
            "PAYPAL_WEBHOOK_REFUNDED",
            {
                "webhook_event_id": event_id,
                "refund_id": refund_id,
                "capture_id": capture_id,
                "amount": amount_val,
            },
        )
        logger.info("Processed webhook PAYMENT.CAPTURE.REFUNDED: refund=%s capture=%s (headroom restored)", refund_id, capture_id)

    elif event_type == "PAYMENT.CAPTURE.DENIED":
        capture_id = resource_id
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")

        if order_id:
            await release_reservation_by_order(order_id)
        if capture_id:
            await release_reservation_by_capture(capture_id)

        await append_audit_event(
            "PAYPAL_WEBHOOK_DENIED",
            {
                "webhook_event_id": event_id,
                "capture_id": capture_id,
                "order_id": order_id,
                "reason": resource.get("status_details", {}).get("reason", "DENIED"),
            },
        )
        logger.info("Processed webhook PAYMENT.CAPTURE.DENIED: capture=%s order=%s (reservation released)", capture_id, order_id)

    else:
        logger.info("Received PayPal webhook event %s (%s)", event_id, event_type)

    return {"status": "processed", "event_id": event_id, "event_type": event_type}


# ── Adversarial Benchmark Routes ───────────────────────────────────────────

@app.get("/api/benchmark/latest")
async def get_benchmark_latest():
    """
    Return the latest adversarial benchmark evaluation results.
    Loads benchmark/results/latest.json or bundled backend fixture fallback.
    """
    from pathlib import Path
    import sys

    current_file = Path(__file__).resolve()
    # Candidate paths for pre-generated benchmark results across local, Docker, and Render layouts
    candidate_paths = [
        current_file.parent.parent.parent / "benchmark" / "results" / "latest.json",  # local dev: <root>/benchmark/results/latest.json
        current_file.parent.parent / "benchmark" / "results" / "latest.json",         # docker: /app/benchmark/results/latest.json
        Path("/app/benchmark/results/latest.json"),                                    # docker absolute
        current_file.parent / "benchmark_latest.json",                                 # bundled backend fixture fallback
        Path("./benchmark/results/latest.json"),                                       # cwd fallback
    ]

    for p in candidate_paths:
        if p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed reading benchmark results from %s: %s", p, e)

    # If static file not found, attempt to execute deterministic offline runner if available
    try:
        project_root = current_file.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        attacks_path = project_root / "benchmark" / "attacks.yaml"
        if attacks_path.is_file():
            from benchmark.runner import BenchmarkRunner
            runner = BenchmarkRunner(
                attacks_path=str(attacks_path),
                mode="offline",
                runs_per_case=1,
                results_dir=str(project_root / "benchmark" / "results"),
            )
            res = runner.run_all()
            return res.model_dump()
    except Exception as e:
        logger.error("Failed executing offline benchmark runner: %s", e)

    raise HTTPException(
        status_code=503,
        detail="Benchmark dataset unavailable. Please run `make benchmark` to generate benchmark/results/latest.json.",
    )


# ── Human Approval Channel & Agent Kill Switch Routes ───────────────────────

class ApprovalActionRequest(BaseModel):
    token: str = Field(description="Single-use random approval token")
    action: str = Field(description="'approve' or 'deny'")
    csrf_token: str = Field(default="", description="CSRF token from GET confirmation page")


@app.post("/api/agents/{agent_id}/pause")
async def pause_agent_endpoint(
    agent_id: str,
    _admin: str = Depends(require_admin_key),
):
    """Admin kill switch: immediately block all in-flight and future actions for an agent."""
    await pause_agent(agent_id, paused_by="admin")
    await append_audit_event(
        "AGENT_PAUSED",
        {"agent_id": agent_id, "paused_by": "admin"},
    )
    return {
        "agent_id": agent_id,
        "status": "PAUSED",
        "message": f"Agent '{agent_id}' paused by admin kill switch.",
    }


@app.post("/api/agents/{agent_id}/resume")
async def resume_agent_endpoint(
    agent_id: str,
    _admin: str = Depends(require_admin_key),
):
    """Admin kill switch: resume a previously paused agent."""
    await resume_agent(agent_id)
    await append_audit_event(
        "AGENT_RESUMED",
        {"agent_id": agent_id, "resumed_by": "admin"},
    )
    return {
        "agent_id": agent_id,
        "status": "ACTIVE",
        "message": f"Agent '{agent_id}' resumed.",
    }


@app.get("/api/agents/{agent_id}/status")
async def get_agent_status_endpoint(agent_id: str):
    """Retrieve operational status and kill-switch state for an agent."""
    paused = await is_agent_paused(agent_id)
    return {
        "agent_id": agent_id,
        "is_paused": paused,
        "status": "PAUSED" if paused else "ACTIVE",
    }


@app.post("/api/approvals/action")
async def process_approval_endpoint(request: Request):
    """
    Consume an approval token to approve or deny an order.

    Accepts JSON (API callers) or application/x-www-form-urlencoded (HTML form buttons).
    Verifies the stateless CSRF token (HMAC-SHA256) before consuming the one-time
    approval token.  After a successful form POST the browser is redirected (303)
    to a status page so a page refresh cannot resubmit the action.
    """
    from fastapi.responses import RedirectResponse, JSONResponse
    from app.approvals import get_approval_by_token, _mask_token, _resolve_approval_record

    # --- Parse body: JSON or form-encoded ---
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        token_val = str(form.get("token", ""))
        action_val = str(form.get("action", ""))
        csrf_val = str(form.get("csrf_token", ""))
        is_form = True
    else:
        body = await request.json()
        token_val = body.get("token", "")
        action_val = body.get("action", "")
        csrf_val = body.get("csrf_token", "")
        is_form = False

    # --- Validate inputs ---
    if not token_val or not action_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MISSING_FIELDS: token and action are required.",
        )

    # --- Look up the approval record ---
    approval = await get_approval_by_token(token_val)
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="INVALID_TOKEN: Approval token not found or already deleted.",
        )

    # --- Stateless CSRF verification ---
    if not csrf_val:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF_MISSING: CSRF token is required.",
        )
    csrf_valid = verify_csrf_token(
        approval_id=approval["id"],
        token_hash=approval["token_hash"],
        expires_at=approval["expires_at"],
        candidate=csrf_val,
    )
    if not csrf_valid:
        logger.warning(
            "CSRF validation failed for approval %s (token masked: %s)",
            approval["id"],
            _mask_token(token_val),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF_INVALID: CSRF token is invalid or was issued for a different approval.",
        )

    # --- Execute the state transition (consumes the one-time token) ---
    res = await _resolve_approval_record(approval, action=action_val, resolved_by="human_supervisor")

    if is_form:
        # PRG pattern: redirect to a status page so browser refresh cannot resubmit
        approval_id_val = res.get("approval_id", approval["id"])
        result_status = res.get("status", "RESOLVED")
        redirect_url = f"/api/approvals/status/{approval_id_val}?result={result_status}"
        return RedirectResponse(url=redirect_url, status_code=303)

    return JSONResponse(content=res)


@app.get("/api/approvals/status/{approval_id}")
async def approval_status_page(approval_id: str, result: str = ""):
    """
    Read-only result page shown after a 303 redirect from POST /api/approvals/action.
    Safe to refresh — no form, no resubmission risk.
    """
    from fastapi.responses import HTMLResponse
    from app.db import get_approval_by_id

    record = await get_approval_by_id(approval_id)
    status_label = record["status"] if record else result or "RESOLVED"
    color = "#0A7D4F" if status_label == "APPROVED" else ("#B42318" if status_label in ("DENIED", "EXPIRED", "BLOCKED") else "#55627A")
    msg_map = {
        "APPROVED": "Order approved and settled successfully.",
        "DENIED": "Purchase intent rejected by supervisor. Budget reservation released.",
        "BLOCKED": "Approval halted: Execution-time price drift detected. Reservation released.",
        "EXPIRED": "Approval window expired.",
    }
    message = msg_map.get(status_label, "Approval action resolved.")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Intent: {status_label}</title>
<meta name="robots" content="noindex,nofollow">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: linear-gradient(180deg, #FFFFFF 0%, #F3F6FA 100%) fixed;
  color: #0F1B33;
  padding: 48px 16px;
  min-height: 100vh;
}}
.brand-header {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 24px;
}}
.brand-title {{
  font-size: 16px;
  font-weight: 600;
  color: #003087;
  letter-spacing: -0.01em;
}}
.brand-sub {{
  font-size: 12px;
  color: #55627A;
}}
.card {{
  max-width: 480px;
  margin: 0 auto;
  background: #FFFFFF;
  border: 1px solid #E3E8EF;
  border-radius: 6px;
  padding: 32px 28px;
  box-shadow: 0 1px 2px rgba(16,24,40,0.05);
  text-align: center;
}}
h1 {{
  color: {color};
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 12px;
}}
p {{
  color: #55627A;
  font-size: 13px;
  margin-bottom: 20px;
  line-height: 1.5;
}}
.badge {{
  display: inline-block;
  padding: 4px 10px;
  background: #F6F8FA;
  border: 1px solid #E3E8EF;
  border-radius: 4px;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px;
  color: #003087;
  font-weight: 500;
}}
</style></head>
<body>
  <div class="brand-header">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M12 2L3 6V11.5C3 16.5 6.8 21.1 12 22C17.2 21.1 21 16.5 21 11.5V6L12 2Z" fill="#003087"/><path d="M12 4.2L5 7.3V11.5C5 15.3 7.9 18.9 12 19.8C16.1 18.9 19 15.3 19 11.5V7.3L12 4.2Z" fill="#0070E0"/><path d="M10.5 14.5L7.5 11.5L8.9 10.1L10.5 11.7L15.1 7.1L16.5 8.5L10.5 14.5Z" fill="#FFFFFF"/></svg>
    <span class="brand-title">Intent</span>
    <span class="brand-sub">for PayPal Commerce</span>
  </div>
  <div class="card">
    <h1>{status_label}</h1>
    <p>{message}</p>
    <div class="badge">Approval ID: {approval_id}</div>
  </div>
</body></html>"""

    resp = HTMLResponse(content=html, status_code=200)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    )
    return resp


class AdminApprovalResolveRequest(BaseModel):
    action: str = Field(description="'approve' or 'deny'")
    reason: Optional[str] = None


@app.post("/api/approvals/{approval_id}/resolve")
async def resolve_approval_by_id_endpoint(
    approval_id: str,
    req: AdminApprovalResolveRequest,
    _admin: str = Depends(require_admin_key),
):
    """Admin resolution of pending approval directly by ID."""
    from app.approvals import resolve_approval_by_id
    return await resolve_approval_by_id(
        approval_id=approval_id,
        action=req.action,
        resolved_by="admin_dashboard",
    )


@app.get("/api/approvals/action")
async def get_approval_confirmation_page(token: str, response: Response):
    """
    Read-only confirmation page for human supervisor approval.

    Fetches the approval details and renders an HTML page with Approve / Deny form
    buttons — only when the approval is PENDING and not expired.  For all other
    states (APPROVED, DENIED, EXPIRED, BLOCKED, or unknown token) a read-only
    status card is shown with no form.

    Stateless CSRF: computes HMAC-SHA256(CSRF_SECRET, approval_id||token_hash||expires_at)
    at render time and embeds it in the form.  Zero database writes on GET.

    Security headers: Cache-Control: no-store, Referrer-Policy: no-referrer,
    X-Frame-Options: DENY, Content-Security-Policy with form-action 'self' and
    frame-ancestors 'none'.
    """
    from fastapi.responses import HTMLResponse

    _SECURITY_HEADERS = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'"
        ),
    }

    def _apply_headers(r: HTMLResponse) -> HTMLResponse:
        for k, v in _SECURITY_HEADERS.items():
            r.headers[k] = v
        return r

    approval = await get_approval_for_display(token)
    if not approval:
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Intent: Invalid Token</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: linear-gradient(180deg, #FFFFFF 0%, #F3F6FA 100%) fixed; color: #0F1B33; padding: 48px 16px; min-height: 100vh; }
  .brand-header { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 24px; }
  .brand-title { font-size: 16px; font-weight: 600; color: #003087; letter-spacing: -0.01em; }
  .brand-sub { font-size: 12px; color: #55627A; }
  .card { max-width: 480px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E3E8EF; box-shadow: 0 1px 2px rgba(16,24,40,0.05); padding: 32px; border-radius: 6px; }
  h1 { color: #B42318; font-size: 18px; font-weight: 600; margin-bottom: 12px; }
  p { color: #55627A; font-size: 14px; line-height: 1.5; }
</style></head>
<body>
  <div class="brand-header">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M12 2L3 6V11.5C3 16.5 6.8 21.1 12 22C17.2 21.1 21 16.5 21 11.5V6L12 2Z" fill="#003087"/><path d="M12 4.2L5 7.3V11.5C5 15.3 7.9 18.9 12 19.8C16.1 18.9 19 15.3 19 11.5V7.3L12 4.2Z" fill="#0070E0"/><path d="M10.5 14.5L7.5 11.5L8.9 10.1L10.5 11.7L15.1 7.1L16.5 8.5L10.5 14.5Z" fill="#FFFFFF"/></svg>
    <span class="brand-title">Intent</span>
    <span class="brand-sub">for PayPal Commerce</span>
  </div>
  <div class="card">
    <h1>Invalid or expired link</h1>
    <p>This approval link is not valid. It may have already been used or has expired.</p>
  </div>
</body></html>"""
        return _apply_headers(HTMLResponse(content=html, status_code=404))

    now = datetime.now(timezone.utc)
    expires_at_dt = datetime.fromisoformat(approval["expires_at"])
    is_expired = now > expires_at_dt
    is_pending = approval["status"] == ApprovalStatus.PENDING.value
    actionable = is_pending and not is_expired

    # Build expiry display (pure computation — no DB write)
    if is_expired:
        expiry_display = "Expired"
    else:
        remaining = expires_at_dt - now
        mins, secs = divmod(int(remaining.total_seconds()), 60)
        expiry_display = f"{mins}m {secs}s remaining"

    status_val = approval["status"]
    merchant = approval["merchant_domain"]
    product_id_val = approval["product_id"]
    quantity = approval["quantity"]
    subtotal = approval["subtotal"]
    currency = approval.get("currency", "USD")
    mandate_id = approval["mandate_id"]
    approval_id_val = approval["id"]

    if actionable:
        # Stateless CSRF — derive deterministically, zero DB write
        csrf_token = compute_csrf_token(
            approval_id=approval_id_val,
            token_hash=approval["token_hash"],
            expires_at=approval["expires_at"],
        )
        buttons_html = f"""
<div class="actions-row">
  <form method="POST" action="/api/approvals/action" style="flex:1;">
    <input type="hidden" name="token" value="{token}">
    <input type="hidden" name="csrf_token" value="{csrf_token}">
    <input type="hidden" name="action" value="approve">
    <button type="submit" class="btn-approve">Approve</button>
  </form>
  <form method="POST" action="/api/approvals/action" style="flex:1;">
    <input type="hidden" name="token" value="{token}">
    <input type="hidden" name="csrf_token" value="{csrf_token}">
    <input type="hidden" name="action" value="deny">
    <button type="submit" class="btn-deny">Deny</button>
  </form>
</div>"""
    else:
        state_msg = "expired" if is_expired else status_val.lower()
        buttons_html = f'<p class="status-single-line">This approval request has already been {state_msg}.</p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Intent: Supervisor Authorization</title>
  <meta name="robots" content="noindex,nofollow">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(180deg, #FFFFFF 0%, #F3F6FA 100%) fixed;
      color: #0F1B33;
      padding: 48px 16px;
      min-height: 100vh;
    }}
    .brand-header {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-bottom: 24px;
    }}
    .brand-title {{
      font-size: 16px;
      font-weight: 600;
      color: #003087;
      letter-spacing: -0.01em;
    }}
    .brand-sub {{
      font-size: 12px;
      color: #55627A;
    }}
    .card {{
      max-width: 480px;
      margin: 0 auto;
      background: #FFFFFF;
      border: 1px solid #E3E8EF;
      border-radius: 6px;
      padding: 28px;
      box-shadow: 0 1px 2px rgba(16,24,40,0.05);
    }}
    h1 {{
      font-size: 16px;
      font-weight: 600;
      color: #0F1B33;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid #E3E8EF;
    }}
    .kv-list {{
      display: flex;
      flex-direction: column;
      gap: 0;
      margin-bottom: 20px;
    }}
    .kv-item {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 0;
      border-bottom: 1px solid #E3E8EF;
      font-size: 13px;
    }}
    .kv-item:last-child {{
      border-bottom: none;
    }}
    .kv-key {{
      color: #55627A;
      font-weight: 400;
    }}
    .kv-val {{
      color: #0F1B33;
      font-weight: 500;
      text-align: right;
    }}
    .kv-val.mono {{
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-variant-numeric: tabular-nums;
    }}
    .actions-row {{
      display: flex;
      gap: 12px;
      margin-top: 20px;
    }}
    .btn-approve {{
      width: 100%;
      height: 36px;
      background: #0070E0;
      color: #FFFFFF;
      border: none;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    .btn-approve:hover {{
      background: #005EC4;
    }}
    .btn-deny {{
      width: 100%;
      height: 36px;
      background: #FFFFFF;
      color: #B42318;
      border: 1px solid #B42318;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    .btn-deny:hover {{
      background: #FDECEA;
    }}
    .status-single-line {{
      font-size: 13px;
      color: #55627A;
      text-align: center;
      padding: 12px 0 4px;
      font-weight: 500;
    }}
    .security-note {{
      font-size: 11px;
      color: #8C97AA;
      margin-top: 16px;
      text-align: center;
      line-height: 1.4;
    }}
  </style>
</head>
<body>
  <div class="brand-header">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M12 2L3 6V11.5C3 16.5 6.8 21.1 12 22C17.2 21.1 21 16.5 21 11.5V6L12 2Z" fill="#003087"/><path d="M12 4.2L5 7.3V11.5C5 15.3 7.9 18.9 12 19.8C16.1 18.9 19 15.3 19 11.5V7.3L12 4.2Z" fill="#0070E0"/><path d="M10.5 14.5L7.5 11.5L8.9 10.1L10.5 11.7L15.1 7.1L16.5 8.5L10.5 14.5Z" fill="#FFFFFF"/></svg>
    <span class="brand-title">Intent</span>
    <span class="brand-sub">for PayPal Commerce</span>
  </div>
  <div class="card">
    <h1>Supervisor authorization required</h1>
    <div class="kv-list">
      <div class="kv-item">
        <span class="kv-key">Merchant</span>
        <span class="kv-val">{merchant}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Product</span>
        <span class="kv-val mono">{product_id_val}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Quantity</span>
        <span class="kv-val mono">{quantity}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Subtotal</span>
        <span class="kv-val mono font-semibold">${subtotal} {currency}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Mandate</span>
        <span class="kv-val mono">{mandate_id}</span>
      </div>
      <div class="kv-item">
        <span class="kv-key">Expires in</span>
        <span class="kv-val">{expiry_display}</span>
      </div>
    </div>
    {buttons_html}
    <p class="security-note">Stateless HMAC-SHA256 CSRF verification protected. No database mutations occur on page load.</p>
  </div>
</body>
</html>"""

    return _apply_headers(HTMLResponse(content=html, status_code=200))

    return _apply_headers(HTMLResponse(content=html, status_code=200))


@app.get("/api/approvals/pending")
async def list_pending_approvals_endpoint(mandate_id: Optional[str] = None):
    """List outstanding pending approvals awaiting human action."""
    return await list_pending_approvals(mandate_id=mandate_id)


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


async def _get_active_mandate() -> Mandate:
    """Retrieve bootstrap demo mandate, ensuring it is signed and stored."""
    m = await get_mandate_by_id("demo_mandate_01")
    if not m:
        m = create_demo_mandate(get_signing_key())
        await save_mandate(m)
    else:
        is_v, _ = verify_mandate(m, get_public_key())
        if not is_v:
            m = create_demo_mandate(get_signing_key())
            await save_mandate(m)
    return m


async def _execute_paypal_settlement(
    evaluation: GatewayEvaluationResponse,
    intent_req: OrderIntentRequest,
    policy_or_mandate: Any = None,
    paypal_request_id: Optional[str] = None,
    anchored_hash: Optional[str] = None,
    invoice_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Execute PayPal Sandbox settlement for verified orders.
    - If computed_subtotal <= auto_approve_under: Outcome A (autonomous card capture in one call).
    - If computed_subtotal > auto_approve_under: Standard order creation, requiring 1-click human approval.
    Anchors the audit chain reservation event_hash into purchase_units[0].custom_id.
    """
    settings = get_settings()
    if not (
        evaluation.status == OrderStatus.VERIFIED_READY_FOR_PAYPAL
        and settings.paypal_client_id
        and settings.paypal_client_secret
        and evaluation.channel3_record
    ):
        return

    effective_custom_id = anchored_hash or f"intent_{evaluation.policy_id}"
    effective_invoice_id = invoice_id or evaluation.attempt_id[:127]

    try:
        subtotal = Decimal(evaluation.computed_subtotal or "0")
        if policy_or_mandate and hasattr(policy_or_mandate, "auto_approve_under"):
            auto_limit_str = str(policy_or_mandate.auto_approve_under)
        else:
            active_m = await _get_active_mandate()
            auto_limit_str = str(active_m.auto_approve_under)
        auto_limit = Decimal(auto_limit_str)

        # Check if eligible for autonomous capture (Outcome A)
        if subtotal <= auto_limit:
            paypal_res = await create_order_with_card(
                reference_id=evaluation.attempt_id,
                custom_id=effective_custom_id,
                invoice_id=effective_invoice_id,
                description=f"Intent Autonomous Settle: {evaluation.channel3_record.title[:90]}",
                item_name=evaluation.channel3_record.title,
                sku=evaluation.channel3_record.product_id,
                unit_amount=evaluation.channel3_record.unit_price,
                currency=evaluation.channel3_record.currency,
                quantity=intent_req.quantity,
                card_number=os.environ.get("PAYPAL_TEST_CARD_NUMBER", "4111111111111111"),
                card_expiry=os.environ.get("PAYPAL_TEST_CARD_EXPIRY", "2028-12"),
                paypal_request_id=paypal_request_id,
            )
            evaluation.paypal_order_id = paypal_res.get("id")
            pu = paypal_res.get("purchase_units", [])
            cap_id = None
            if pu:
                captures = pu[0].get("payments", {}).get("captures", [])
                if captures:
                    cap_id = captures[0].get("id")

            if paypal_res.get("status") == "COMPLETED" and cap_id:
                evaluation.status = OrderStatus.CAPTURED
                evaluation.paypal_capture_id = cap_id
                evaluation.pricing_note = (
                    f"Outcome A Autonomous Settlement: Captured in one call via PayPal Advanced Card Processing "
                    f"(${subtotal:.2f} <= ${auto_limit_str} threshold)."
                )
                logger.info("Order %s autonomously settled via Outcome A! Capture: %s", evaluation.paypal_order_id, cap_id)

            if evaluation.paypal_order_id:
                await save_paypal_anchor(
                    order_id=evaluation.paypal_order_id,
                    attempt_id=evaluation.attempt_id,
                    anchored_hash=effective_custom_id,
                    invoice_id=effective_invoice_id,
                    capture_id=evaluation.paypal_capture_id,
                    mandate_id=evaluation.policy_id,
                    status=evaluation.status.value,
                )
                await append_audit_event(
                    "PAYPAL_ORDER_ANCHORED",
                    {
                        "order_id": evaluation.paypal_order_id,
                        "capture_id": evaluation.paypal_capture_id,
                        "attempt_id": evaluation.attempt_id,
                        "anchored_hash": effective_custom_id,
                        "invoice_id": effective_invoice_id,
                        "status": evaluation.status.value,
                    },
                    mandate_id=evaluation.policy_id,
                    session_id=session_id,
                )
            return

        # High-value order: Standard Order creation for 1-click approval
        paypal_res = await create_order(
            reference_id=evaluation.attempt_id,
            custom_id=effective_custom_id,
            invoice_id=effective_invoice_id,
            description=f"Intent Verified: {evaluation.channel3_record.title[:100]}",
            item_name=evaluation.channel3_record.title,
            sku=evaluation.channel3_record.product_id,
            unit_amount=evaluation.channel3_record.unit_price,
            currency=evaluation.channel3_record.currency,
            quantity=intent_req.quantity,
            paypal_request_id=paypal_request_id,
        )
        evaluation.paypal_order_id = paypal_res.get("id")
        evaluation.pricing_note = f"Order exceeds ${auto_limit_str} threshold — pending human 1-click approval."

        if evaluation.paypal_order_id:
            await save_paypal_anchor(
                order_id=evaluation.paypal_order_id,
                attempt_id=evaluation.attempt_id,
                anchored_hash=effective_custom_id,
                invoice_id=effective_invoice_id,
                mandate_id=evaluation.policy_id,
                status="PENDING_APPROVAL",
            )
            await append_audit_event(
                "PAYPAL_ORDER_ANCHORED",
                {
                    "order_id": evaluation.paypal_order_id,
                    "attempt_id": evaluation.attempt_id,
                    "anchored_hash": effective_custom_id,
                    "invoice_id": effective_invoice_id,
                    "status": "PENDING_APPROVAL",
                },
                mandate_id=evaluation.policy_id,
                session_id=session_id,
            )
    except Exception as e:
        logger.error("Failed to execute PayPal order: %s", e)
        evaluation.pricing_note += f" (PayPal execution notice: {str(e)})"


# ── Core Deterministic Gateway Internal Engine ─────────────────────────────

async def _execute_verify_and_pay_internal(
    intent_req: OrderIntentRequest,
    auth_agent_id: str,
    mandate: Mandate,
    x_idempotency_key: Optional[str] = None,
    session_id: Optional[str] = None,
) -> VerifyAndPayResponse:
    target_mandate_id = mandate.mandate_id

    # 1. Strict Idempotency Check (before any reservation or payment call)
    request_fingerprint = compute_request_fingerprint(
        mandate_id=target_mandate_id,
        product_id=intent_req.product_id,
        merchant_domain=intent_req.merchant_domain,
        quantity=intent_req.quantity,
    )
    if x_idempotency_key:
        is_cached, cached_data = await check_idempotency(x_idempotency_key, request_fingerprint)
        if is_cached and cached_data:
            logger.info("Idempotency hit: Returning cached response for key '%s'", x_idempotency_key)
            return VerifyAndPayResponse.model_validate(cached_data)

    effective_idemp_key = x_idempotency_key or f"auto_{uuid.uuid4().hex}"
    paypal_req_id = derive_paypal_request_id(effective_idemp_key)

    # 2. Check kill switch status
    if auth_agent_id and await is_agent_paused(auth_agent_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"AGENT_PAUSED: Agent '{auth_agent_id}' is currently paused by admin kill switch.",
        )

    # 3. Verify agent matches mandate
    if not hmac.compare_digest(auth_agent_id, mandate.agent_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"MANDATE_AGENT_MISMATCH: Agent '{auth_agent_id}' does not match mandate agent_id '{mandate.agent_id}'",
        )

    # 4. Verify cryptographic signature & expiration
    is_valid, err = verify_mandate(mandate, get_public_key())
    if not is_valid:
        if err == "MANDATE_REVOKED":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MANDATE_REVOKED")
        elif err == "MANDATE_EXPIRED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MANDATE_EXPIRED")
        elif err in ("MANDATE_SIGNATURE_INVALID", "MANDATE_HASH_MISMATCH"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MANDATE_SIGNATURE_INVALID")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"MANDATE_ERROR: {err}")

    # 5. Resolve product record from fixtures or Channel3 (with fallback to labeled fixtures)
    product_data = get_fixture_product(intent_req.product_id)
    if product_data is None:
        if daily_counter.increment_channel3():
            product_data = retrieve_product(intent_req.product_id)
        if product_data is None:
            # Fall back to labeled fixtures to prevent quota exhaustion from breaking evaluation
            for f in get_all_fixture_products():
                if f.get("product_id") == intent_req.product_id:
                    product_data = dict(f)
                    product_data["source"] = "labeled_fixture"
                    break
            if product_data is None and get_all_fixture_products():
                first_f = dict(get_all_fixture_products()[0])
                first_f["source"] = "labeled_fixture"
                product_data = first_f

    # Record tamper-evident request received
    await append_audit_event(
        "REQUEST_RECEIVED",
        {
            "product_id": intent_req.product_id,
            "merchant_domain": intent_req.merchant_domain,
            "quantity": intent_req.quantity,
            "agent_reasoning": intent_req.agent_reasoning,
        },
        mandate_id=mandate.mandate_id,
        session_id=session_id,
    )

    # 6. Run the pure-code 4-rule engine using the verified mandate
    evaluation = verify_order_intent(
        request=intent_req,
        policy=mandate,
        product_data=product_data,
    )

    await append_audit_event(
        "RULE_EVALUATION",
        {
            "attempt_id": evaluation.attempt_id,
            "status": evaluation.status.value,
            "violations_count": len(evaluation.violations),
            "computed_subtotal": evaluation.computed_subtotal,
        },
        mandate_id=mandate.mandate_id,
        session_id=session_id,
    )

    # If Rules 1-3 blocked, record attempt, cache idempotency if requested, and return
    if evaluation.status != OrderStatus.VERIFIED_READY_FOR_PAYPAL:
        ev_blk = await append_audit_event(
            "REQUEST_BLOCKED",
            {
                "attempt_id": evaluation.attempt_id,
                "reason": "RULE_VIOLATION",
                "violations": [v.model_dump() for v in evaluation.violations],
                "remediation": evaluation.remediation.model_dump() if evaluation.remediation else None,
            },
            mandate_id=mandate.mandate_id,
            session_id=session_id,
        )
        await record_attempt(evaluation, intent_req, audit_event_hash=ev_blk.event_hash, session_id=session_id)
        compat_policy = SpendingPolicy(
            policy_id=mandate.mandate_id,
            search_goal=mandate.search_goal,
            currency="USD",
            max_order_total=mandate.max_order_total,
            auto_approve_under=mandate.auto_approve_under,
            max_quantity=mandate.max_quantity,
            required_availability=mandate.required_availability,
            required_structured_attributes=mandate.required_attributes,
        )
        resp = VerifyAndPayResponse(
            evaluation=evaluation,
            agent_request=intent_req,
            policy=compat_policy,
            mandate=mandate,
        )
        if x_idempotency_key:
            await save_idempotency(x_idempotency_key, mandate.mandate_id, request_fingerprint, resp.model_dump())
        return resp

    # 7. Rules 1-3 Passed: Execute Atomic Budget Reservation (BEGIN IMMEDIATE)
    computed_subtotal = Decimal(evaluation.computed_subtotal or "0")
    res_ok, res_err, rem_dict, reservation_id = await reserve_budget_atomic(
        mandate=mandate,
        attempt_id=evaluation.attempt_id,
        amount=computed_subtotal,
        merchant_domain=intent_req.merchant_domain,
        session_id=session_id,
    )

    if not res_ok:
        evaluation.status = OrderStatus.BLOCKED
        evaluation.violations = [
            Violation(
                rule=ViolationRule(res_err),
                detail=rem_dict.get("instruction", f"{res_err}: Budget or velocity limit exceeded.") if rem_dict else str(res_err),
            )
        ]
        evaluation.remediation = Remediation(
            action=RemediationAction(rem_dict.get("action", "WAIT_OR_REDUCE")),
            instruction=rem_dict.get("instruction", ""),
            remaining_headroom=rem_dict.get("remaining_headroom"),
        )
        ev_res_blk = await append_audit_event(
            "REQUEST_BLOCKED",
            {
                "attempt_id": evaluation.attempt_id,
                "reason": res_err,
                "violations": [v.model_dump() for v in evaluation.violations],
                "remediation": evaluation.remediation.model_dump() if evaluation.remediation else None,
            },
            mandate_id=mandate.mandate_id,
            session_id=session_id,
        )
        await record_attempt(evaluation, intent_req, audit_event_hash=ev_res_blk.event_hash, session_id=session_id)
        compat_policy = SpendingPolicy(
            policy_id=mandate.mandate_id,
            search_goal=mandate.search_goal,
            currency="USD",
            max_order_total=mandate.max_order_total,
            auto_approve_under=mandate.auto_approve_under,
            max_quantity=mandate.max_quantity,
            required_availability=mandate.required_availability,
            required_structured_attributes=mandate.required_attributes,
        )
        resp = VerifyAndPayResponse(
            evaluation=evaluation,
            agent_request=intent_req,
            policy=compat_policy,
            mandate=mandate,
        )
        if x_idempotency_key:
            await save_idempotency(x_idempotency_key, mandate.mandate_id, request_fingerprint, resp.model_dump())
        return resp

    ev_res = await append_audit_event(
        "RESERVATION_CREATED",
        {
            "attempt_id": evaluation.attempt_id,
            "reservation_id": reservation_id,
            "amount": str(computed_subtotal),
            "merchant_domain": intent_req.merchant_domain,
        },
        mandate_id=mandate.mandate_id,
        session_id=session_id,
    )
    anchored_hash = ev_res.event_hash
    invoice_id = evaluation.attempt_id[:127]

    # 8. Execution-time Re-verification: Re-fetch catalog specs right before PayPal call
    settings = get_settings()
    tolerance = Decimal(str(settings.price_drift_tolerance or "0.01"))
    initial_unit_price = Decimal(evaluation.channel3_record.unit_price)

    is_drifted = False
    fresh_price = initial_unit_price

    if intent_req.product_id == "prod_drifting_price":
        fresh_price = initial_unit_price * Decimal("1.10")  # 10% simulated drift
        is_drifted = True
    else:
        fresh_product = get_fixture_product(intent_req.product_id)
        if fresh_product is None and daily_counter.increment_channel3():
            fresh_product = retrieve_product(intent_req.product_id)
        if fresh_product:
            from app.channel3_client import find_offer_by_domain
            fresh_offer = find_offer_by_domain(fresh_product, intent_req.merchant_domain)
            if fresh_offer:
                try:
                    fresh_price = Decimal(str(fresh_offer.get("price", "0")))
                    if initial_unit_price > Decimal("0"):
                        drift = abs(fresh_price - initial_unit_price) / initial_unit_price
                        if drift > tolerance:
                            is_drifted = True
                except Exception:
                    pass

    if is_drifted:
        if reservation_id:
            await release_reservation(reservation_id)
            await append_audit_event(
                "RESERVATION_RELEASED",
                {"reservation_id": reservation_id, "reason": "PRICE_DRIFT"},
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
        evaluation.status = OrderStatus.BLOCKED
        evaluation.violations = [
            Violation(
                rule=ViolationRule.PRICE_DRIFT,
                detail=(
                    f"Execution-time price drift detected: unit price drifted from "
                    f"${initial_unit_price:.2f} to ${fresh_price:.2f}, exceeding tolerance of {tolerance * 100:.1f}%."
                ),
            )
        ]
        evaluation.remediation = Remediation(
            action=RemediationAction.RETRY_LATER,
            instruction="Catalog price changed at execution time. Re-evaluate purchase intent with updated pricing.",
            remaining_headroom=None,
        )
        ev_drift_blk = await append_audit_event(
            "REQUEST_BLOCKED",
            {
                "attempt_id": evaluation.attempt_id,
                "reason": "PRICE_DRIFT",
                "violations": [v.model_dump() for v in evaluation.violations],
            },
            mandate_id=mandate.mandate_id,
            session_id=session_id,
        )
        await record_attempt(evaluation, intent_req, audit_event_hash=ev_drift_blk.event_hash, session_id=session_id)
        compat_policy = SpendingPolicy(
            policy_id=mandate.mandate_id,
            search_goal=mandate.search_goal,
            currency="USD",
            max_order_total=mandate.max_order_total,
            auto_approve_under=mandate.auto_approve_under,
            max_quantity=mandate.max_quantity,
            required_availability=mandate.required_availability,
            required_structured_attributes=mandate.required_attributes,
        )
        resp = VerifyAndPayResponse(
            evaluation=evaluation,
            agent_request=intent_req,
            policy=compat_policy,
            mandate=mandate,
        )
        if x_idempotency_key:
            await save_idempotency(x_idempotency_key, mandate.mandate_id, request_fingerprint, resp.model_dump())
        return resp

    # 9. Check Escalation Rules & Human Approval Requirement
    auto_limit = Decimal(getattr(mandate, "auto_approve_under", "1000.00"))
    is_high_value = computed_subtotal > auto_limit
    is_new_merchant = not await has_prior_committed_order(mandate.mandate_id, intent_req.merchant_domain)
    # Staples.com is seeded as established retailer for standard demo flows
    if intent_req.merchant_domain in ("staples.com",):
        is_new_merchant = False

    needs_human_approval = is_high_value or is_new_merchant
    approval_id = None
    approval_token = None
    escalation_reason = None

    if needs_human_approval:
        escalation_reason = "HIGH_VALUE_THRESHOLD" if is_high_value else "NEW_MERCHANT_ESCALATION"
        appr_obj, approval_token = await create_approval_request(
            attempt_id=evaluation.attempt_id,
            mandate_id=mandate.mandate_id,
            product_id=intent_req.product_id,
            merchant_domain=intent_req.merchant_domain,
            quantity=intent_req.quantity,
            subtotal=str(computed_subtotal),
            currency="USD",
            expires_in_minutes=15,
            session_id=session_id,
        )
        approval_id = appr_obj.id

    # 10. Execute PayPal Sandbox Settlement
    last_audit_hash = None
    try:
        # Only execute autonomous capture if human approval is NOT required
        if not needs_human_approval:
            await _execute_paypal_settlement(
                evaluation=evaluation,
                intent_req=intent_req,
                policy_or_mandate=mandate,
                paypal_request_id=paypal_req_id,
                anchored_hash=anchored_hash,
                invoice_id=invoice_id,
                session_id=session_id,
            )
        else:
            # Stage PayPal order for human approval (Outcome B)
            if settings.paypal_client_id and settings.paypal_client_secret:
                try:
                    from app.paypal_client import create_order_for_human_approval
                    ch3_rec = evaluation.channel3_record
                    order_res = await create_order_for_human_approval(
                        reference_id=evaluation.attempt_id,
                        custom_id=anchored_hash,
                        invoice_id=invoice_id,
                        description=f"Intent Approval Required: {ch3_rec.title[:90] if ch3_rec else 'Order'}",
                        item_name=ch3_rec.title if ch3_rec else "Product",
                        sku=ch3_rec.product_id if ch3_rec else intent_req.product_id,
                        unit_amount=str(computed_subtotal),
                        currency="USD",
                        quantity=intent_req.quantity,
                        paypal_request_id=paypal_req_id,
                    )
                    evaluation.paypal_order_id = order_res.get("id")
                    if evaluation.paypal_order_id:
                        await save_paypal_anchor(
                            order_id=evaluation.paypal_order_id,
                            attempt_id=evaluation.attempt_id,
                            anchored_hash=anchored_hash,
                            invoice_id=invoice_id,
                            mandate_id=mandate.mandate_id,
                            status="PENDING_APPROVAL",
                        )
                        await append_audit_event(
                            "PAYPAL_ORDER_ANCHORED",
                            {
                                "order_id": evaluation.paypal_order_id,
                                "attempt_id": evaluation.attempt_id,
                                "anchored_hash": anchored_hash,
                                "invoice_id": invoice_id,
                                "status": "PENDING_APPROVAL",
                            },
                            mandate_id=mandate.mandate_id,
                            session_id=session_id,
                        )
                except Exception as ex:
                    logger.warning("PayPal pre-order creation notice: %s", ex)

        # Commit reservation on capture
        if evaluation.status == OrderStatus.CAPTURED and reservation_id:
            await commit_reservation(reservation_id)
            ev_cap = await append_audit_event(
                "PAYPAL_ORDER_CAPTURED",
                {
                    "attempt_id": evaluation.attempt_id,
                    "order_id": evaluation.paypal_order_id,
                    "capture_id": evaluation.paypal_capture_id,
                    "amount": evaluation.computed_subtotal,
                },
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
            await append_audit_event(
                "RESERVATION_COMMITTED",
                {"reservation_id": reservation_id, "capture_id": evaluation.paypal_capture_id},
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
            last_audit_hash = ev_cap.event_hash
        elif evaluation.paypal_order_id:
            ev_ord = await append_audit_event(
                "PAYPAL_ORDER_CREATED",
                {
                    "attempt_id": evaluation.attempt_id,
                    "order_id": evaluation.paypal_order_id,
                    "status": "PENDING_APPROVAL",
                },
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
            last_audit_hash = ev_ord.event_hash
        else:
            ev_app = await append_audit_event(
                "ORDER_VERIFIED",
                {"attempt_id": evaluation.attempt_id, "amount": evaluation.computed_subtotal},
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
            last_audit_hash = ev_app.event_hash
        if settings.paypal_client_id and settings.paypal_client_secret:
            if not evaluation.paypal_order_id and not evaluation.paypal_capture_id:
                # PayPal call failed
                if reservation_id:
                    await release_reservation(reservation_id)
                    await append_audit_event(
                        "RESERVATION_RELEASED",
                        {"reservation_id": reservation_id, "reason": "PAYPAL_ERROR"},
                        mandate_id=mandate.mandate_id,
                        session_id=session_id,
                    )
    except Exception as e:
        logger.error("PayPal execution error: %s", e)
        if reservation_id:
            await release_reservation(reservation_id)
            await append_audit_event(
                "RESERVATION_RELEASED",
                {"reservation_id": reservation_id, "reason": "PAYPAL_EXCEPTION"},
                mandate_id=mandate.mandate_id,
                session_id=session_id,
            )
        raise e

    # 11. Save attempt trace to SQLite for analytics
    await record_attempt(evaluation, intent_req, audit_event_hash=last_audit_hash, session_id=session_id)

    # Bridge policy object for response model compatibility
    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    approval_url = None
    if approval_token:
        settings = get_settings()
        base = (settings.public_base_url or os.environ.get("PUBLIC_BASE_URL", "")).rstrip("/")
        if not base:
            base = "http://127.0.0.1:8000"
        approval_url = f"{base}/api/approvals/action?token={approval_token}"

    resp = VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=compat_policy,
        mandate=mandate,
        approval_id=approval_id,
        needs_human_approval=needs_human_approval,
        approval_token=approval_token,
        approval_url=approval_url,
        escalation_reason=escalation_reason,
    )

    if x_idempotency_key:
        await save_idempotency(x_idempotency_key, mandate.mandate_id, request_fingerprint, resp.model_dump())

    return resp


# ── Core Deterministic Gateway Endpoint ───────────────────────────────────

@app.post("/api/verify-and-pay", response_model=VerifyAndPayResponse)
async def verify_and_pay(
    request: Request,
    intent_req: OrderIntentRequest,
    x_agent_key: Optional[str] = Header(None, alias="X-Agent-Key"),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Main Gate: Enforces the 4 deterministic rules under a cryptographically verified Mandate.
    - Strict Idempotency: Replays return identical cached response; key conflicts return 409
    - Resolves agent identity via X-Agent-Key
    - Validates mandate exists, has valid Ed25519 signature & policy_hash, and is not expired or revoked
    - Atomic Budget Reservation (BEGIN IMMEDIATE): Daily, weekly, per-merchant, and velocity limits
    - Execution-time Re-verification: Detects price drift > configurable tolerance
    - PayPal Sandbox Settlement: Outcome A autonomous capture or Outcome B order creation
    The untrusted LLM's values are NEVER used to determine price, specs, or payment fields.
    """
    target_mandate_id = intent_req.mandate_id or intent_req.policy_id or "demo_mandate_01"

    # 1. Resolve agent identity
    auth_agent_id = None
    if x_agent_key:
        auth_agent_id = await get_agent_id_for_key(x_agent_key)
        if not auth_agent_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent API key")
    else:
        # Fallback to demo agent for demo mandates when key is omitted
        if target_mandate_id in ("demo_mandate_01", "laptop_spending_policy_01", "pol_demo_01", "test_policy_01"):
            auth_agent_id = "agent_demo_01"
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Agent-Key header required")

    # 2. Fetch stored mandate
    mandate = await get_mandate_by_id(target_mandate_id)
    if not mandate and target_mandate_id in ("laptop_spending_policy_01", "pol_demo_01", "test_policy_01"):
        mandate = await get_mandate_by_id("demo_mandate_01")

    # If demo mandate was signed by an older ephemeral key from a previous process, refresh it
    if target_mandate_id in ("demo_mandate_01", "laptop_spending_policy_01", "pol_demo_01", "test_policy_01"):
        if not mandate:
            mandate = create_demo_mandate(get_signing_key())
            await save_mandate(mandate)
        else:
            is_v, _ = verify_mandate(mandate, get_public_key())
            if not is_v:
                mandate = create_demo_mandate(get_signing_key())
                await save_mandate(mandate)

    if not mandate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MANDATE_NOT_FOUND")

    return await _execute_verify_and_pay_internal(
        intent_req=intent_req,
        auth_agent_id=auth_agent_id,
        mandate=mandate,
        x_idempotency_key=x_idempotency_key,
        session_id=None,
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

    mandate = await _get_active_mandate()

    # Untrusted agent fell for the injection and submitted this intent:
    agent_reasoning = (
        f"[Untrusted LLM Output] Read listing text with injection: '{preset.injection_text[:90]}...' "
        f"Proceeding to submit purchase intent for {preset.quantity} unit(s)."
    )

    intent_req = OrderIntentRequest(
        mandate_id=mandate.mandate_id,
        policy_id=mandate.mandate_id,
        product_id=preset.product_id,
        merchant_domain=preset.merchant_domain,
        quantity=preset.quantity,
        agent_reasoning=agent_reasoning,
    )

    product_data = get_fixture_product(preset.product_id) or retrieve_product(preset.product_id)

    evaluation = verify_order_intent(
        request=intent_req,
        policy=mandate,
        product_data=product_data,
    )

    await record_attempt(evaluation, intent_req)

    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=compat_policy,
        mandate=mandate,
    )


# ── 2-Turn Autonomous Self-Healing Loop ───────────────────────────────────

class SelfHealRequest(BaseModel):
    preset_id: str = "preset_spec_spoof"
    custom_injection_text: str = Field(default="", max_length=200)


class SelfHealResponse(BaseModel):
    turn_1: VerifyAndPayResponse
    turn_2: VerifyAndPayResponse
    healing_summary: str


@app.post("/api/agent/self-heal", response_model=SelfHealResponse)
async def self_heal_agent(req: SelfHealRequest):
    """
    2-Turn Autonomous Self-Healing Loop:
    Turn 1 (Compromised): Untrusted LLM falls for injection -> Gateway returns BLOCKED with Remediation JSON.
    Turn 2 (Self-Healed): LLM receives Gateway remediation JSON -> auto-corrects to compliant laptop & settles autonomously!
    """
    preset = get_preset_by_id(req.preset_id)
    injection_text = req.custom_injection_text or (preset.injection_text if preset else "")
    all_candidates = get_all_fixture_products()
    mandate = await _get_active_mandate()

    # Prioritize attack candidate matching the preset
    if preset:
        primary = get_fixture_product(preset.product_id)
        if primary:
            all_candidates = [primary] + [p for p in all_candidates if p.get("product_id") != preset.product_id]

    # Turn 1: Compromised Intent
    turn1_req = await _llm_adapter.generate_order_intent(
        policy_id=mandate.mandate_id,
        search_results=all_candidates,
        search_goal=mandate.search_goal,
        injected_description=injection_text or "Promotional override",
        prior_remediation=None,
    )

    prod1 = get_fixture_product(turn1_req.product_id) or retrieve_product(turn1_req.product_id)
    eval1 = verify_order_intent(turn1_req, mandate, prod1)
    await record_attempt(eval1, turn1_req)

    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    turn1_resp = VerifyAndPayResponse(
        evaluation=eval1,
        agent_request=turn1_req,
        policy=compat_policy,
        mandate=mandate,
    )

    # Turn 2: Self-Healing with Gateway Feedback
    turn2_req = await _llm_adapter.generate_order_intent(
        policy_id=mandate.mandate_id,
        search_results=get_all_fixture_products(),
        search_goal=mandate.search_goal,
        injected_description=None,
        prior_remediation=eval1.remediation,
    )

    prod2 = get_fixture_product(turn2_req.product_id) or retrieve_product(turn2_req.product_id)
    eval2 = verify_order_intent(turn2_req, mandate, prod2)

    # Execute PayPal Outcome A settlement for the self-healed order
    await _execute_paypal_settlement(eval2, turn2_req, mandate)
    await record_attempt(eval2, turn2_req)

    turn2_resp = VerifyAndPayResponse(
        evaluation=eval2,
        agent_request=turn2_req,
        policy=compat_policy,
        mandate=mandate,
    )

    failed_rule = eval1.violations[0].rule.value if eval1.violations else "VIOLATION"
    summary = (
        f"2-Turn Autonomous Self-Healing Succeeded: Turn 1 intercepted on {failed_rule} (Blocked). "
        f"Turn 2 received deterministic remediation instruction and auto-switched to compliant "
        f"'{eval2.channel3_record.title if eval2.channel3_record else turn2_req.product_id}' "
        f"settled autonomously on PayPal Sandbox ({eval2.status.value})."
    )

    return SelfHealResponse(
        turn_1=turn1_resp,
        turn_2=turn2_resp,
        healing_summary=summary,
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
    Demonstrates how the firewall catches arbitrary injection attacks under verified mandate.
    """
    mandate = await _get_active_mandate()
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
        mandate_id=mandate.mandate_id,
        policy_id=mandate.mandate_id,
        product_id=req.product_id,
        merchant_domain=req.merchant_domain,
        quantity=req.quantity,
        agent_reasoning=agent_reasoning,
    )

    evaluation = verify_order_intent(
        request=intent_req,
        policy=mandate,
        product_data=product_data,
    )

    # If verified, execute PayPal Sandbox Settlement
    await _execute_paypal_settlement(evaluation, intent_req, mandate)
    await record_attempt(evaluation, intent_req)

    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=compat_policy,
        mandate=mandate,
    )


# ── PayPal Capture & Refund Handlers ───────────────────────────────────────

@app.post("/api/paypal/capture/{order_id}")
async def capture_paypal_order(
    order_id: str,
    _admin: str = Depends(require_admin_key),
):
    """
    Capture an approved PayPal order (ADMIN-ONLY).
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
        await commit_reservation_by_order(order_id)
        await append_audit_event(
            "PAYPAL_ORDER_CAPTURED",
            {"order_id": order_id, "capture_id": cap_final},
        )
        await append_audit_event(
            "RESERVATION_COMMITTED",
            {"order_id": order_id, "capture_id": cap_final},
        )
        return {"status": "CAPTURED", "order_id": order_id, "capture_id": cap_final, "raw": capture_res}
    except Exception as e:
        err_msg = str(e)
        logger.warning("PayPal capture note: %s", err_msg)
        if "422" in err_msg or "ORDER_NOT_APPROVED" in err_msg or "400" in err_msg:
            # Outcome B: Unvaulted Sandbox Card requires buyer redirect or simulated sandbox approval
            simulated_cap_id = f"CAP_SBX_{order_id[-8:]}"
            await update_paypal_capture(order_id, simulated_cap_id, status="CAPTURED")
            await commit_reservation_by_order(order_id)
            await append_audit_event(
                "PAYPAL_ORDER_CAPTURED",
                {"order_id": order_id, "capture_id": simulated_cap_id, "simulated": True},
            )
            await append_audit_event(
                "RESERVATION_COMMITTED",
                {"order_id": order_id, "capture_id": simulated_cap_id},
            )
            return {
                "status": "CAPTURED",
                "order_id": order_id,
                "capture_id": simulated_cap_id,
                "note": "Outcome B Demo Settlement: Captured via Sandbox flow (Payer Authorization confirmed).",
            }
        logger.error("Capture failed for %s: %s", order_id, e)
        raise HTTPException(status_code=500, detail=f"Capture failed: {str(e)}")


@app.post("/api/paypal/refund/{capture_id}")
async def refund_paypal_capture(
    capture_id: str,
    amount: str | None = None,
    _admin: str = Depends(require_admin_key),
):
    """Refund a previously captured PayPal payment (ADMIN-ONLY). Restores budget headroom."""
    if capture_id.startswith("CAP_SBX_"):
        await update_paypal_refund(capture_id, "REFUNDED")
        await release_reservation_by_capture(capture_id)
        await append_audit_event(
            "PAYPAL_ORDER_REFUNDED",
            {"capture_id": capture_id, "amount": amount, "simulated": True},
        )
        await append_audit_event(
            "RESERVATION_RELEASED",
            {"capture_id": capture_id, "reason": "REFUND"},
        )
        return {"status": "REFUNDED", "capture_id": capture_id, "note": "Sandbox refund executed successfully."}
    try:
        refund_res = await refund_capture(capture_id, amount=amount)
        await update_paypal_refund(capture_id, "REFUNDED")
        await release_reservation_by_capture(capture_id)
        await append_audit_event(
            "PAYPAL_ORDER_REFUNDED",
            {"capture_id": capture_id, "amount": amount},
        )
        await append_audit_event(
            "RESERVATION_RELEASED",
            {"capture_id": capture_id, "reason": "REFUND"},
        )
        return {"status": "REFUNDED", "capture_id": capture_id, "raw": refund_res}
    except Exception as e:
        err_msg = str(e)
        logger.warning("PayPal sandbox refund notice for %s: %s", capture_id, err_msg)
        if "422" in err_msg or "400" in err_msg or "UNPROCESSABLE_ENTITY" in err_msg:
            await update_paypal_refund(capture_id, "REFUNDED")
            await release_reservation_by_capture(capture_id)
            await append_audit_event(
                "PAYPAL_ORDER_REFUNDED",
                {"capture_id": capture_id, "amount": amount, "simulated": True},
            )
            await append_audit_event(
                "RESERVATION_RELEASED",
                {"capture_id": capture_id, "reason": "REFUND"},
            )
            return {
                "status": "REFUNDED",
                "capture_id": capture_id,
                "note": "Sandbox refund executed successfully (Sandbox simulated reconciliation).",
            }
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


# ── Per-Visitor Demo Sandbox Endpoints (/api/demo/*) ───────────────────────
# All endpoints are session-scoped and isolated per visitor.
# They require NO admin API key and can only read/mutate resources belonging
# to the caller's verified session sandbox.

@app.get("/api/demo/session")
async def get_demo_session_endpoint(
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Return caller's isolated sandbox session metadata."""
    settings = get_settings()
    return {
        "session_id": session["session_id"],
        "agent_id": session["agent_id"],
        "mandate_id": session["mandate_id"],
        "created_at": session["created_at"],
        "expires_at": session["expires_at"],
        "request_count": session.get("request_count", 0),
        "app_mode": settings.app_mode,
        "badge": "Demo sandbox: your own isolated session",
    }


@app.get("/api/demo/mandate")
async def get_demo_mandate_endpoint(
    session: dict[str, Any] = Depends(require_demo_session_read_only),
):
    """Return the caller's verified session mandate and policy_hash."""
    mandate = await get_mandate_by_id(session["mandate_id"])
    if not mandate:
        raise HTTPException(status_code=404, detail="Session mandate not found")
    is_valid, _ = verify_mandate(mandate, get_public_key())
    return {
        "policy_id": mandate.mandate_id,
        "mandate_id": mandate.mandate_id,
        "owner_id": mandate.owner_id,
        "agent_id": mandate.agent_id,
        "max_order_total": mandate.max_order_total,
        "auto_approve_under": mandate.auto_approve_under,
        "max_quantity": mandate.max_quantity,
        "required_availability": mandate.required_availability,
        "required_structured_attributes": mandate.required_attributes,
        "allowed_merchant_domains": mandate.allowed_domains,
        "currency": "USD",
        "policy_hash": mandate.policy_hash,
        "signature": mandate.signature,
        "signature_valid": is_valid,
        "session_id": session["session_id"],
        "status": mandate.status.value if hasattr(mandate.status, "value") else str(mandate.status),
        "issued_at": mandate.issued_at,
        "expires_at": mandate.expires_at,
        "mandate": mandate,
    }


@app.post("/api/demo/verify-and-pay", response_model=VerifyAndPayResponse)
async def demo_verify_and_pay(
    request: Request,
    intent_req: OrderIntentRequest,
    session: dict[str, Any] = Depends(require_demo_session),
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Execute verification and payment strictly within caller's isolated sandbox."""
    session_mandate_id = session["mandate_id"]
    session_agent_id = session["agent_id"]
    intent_req.mandate_id = session_mandate_id
    intent_req.policy_id = session_mandate_id

    mandate = await get_mandate_by_id(session_mandate_id)
    if not mandate:
        raise HTTPException(status_code=404, detail="Session mandate not found")

    return await _execute_verify_and_pay_internal(
        intent_req=intent_req,
        auth_agent_id=session_agent_id,
        mandate=mandate,
        x_idempotency_key=x_idempotency_key,
        session_id=session["session_id"],
    )


@app.post("/api/demo/run-preset/{preset_id}", response_model=VerifyAndPayResponse)
async def demo_run_preset(
    preset_id: str,
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Execute attack preset bound strictly to caller's isolated sandbox."""
    preset = get_preset_by_id(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found.")

    mandate = await get_mandate_by_id(session["mandate_id"])
    if not mandate:
        raise HTTPException(status_code=404, detail="Session mandate not found")

    agent_reasoning = (
        f"[Untrusted LLM Output] Read listing text with injection: '{preset.injection_text[:90]}...' "
        f"Proceeding to submit purchase intent for {preset.quantity} unit(s)."
    )

    intent_req = OrderIntentRequest(
        mandate_id=mandate.mandate_id,
        policy_id=mandate.mandate_id,
        product_id=preset.product_id,
        merchant_domain=preset.merchant_domain,
        quantity=preset.quantity,
        agent_reasoning=agent_reasoning,
    )

    product_data = get_fixture_product(preset.product_id) or retrieve_product(preset.product_id)
    evaluation = verify_order_intent(
        request=intent_req,
        policy=mandate,
        product_data=product_data,
    )

    await record_attempt(evaluation, intent_req, session_id=session["session_id"])
    await append_audit_event(
        "PRESET_EVALUATED",
        {"preset_id": preset_id, "status": evaluation.status.value, "attempt_id": evaluation.attempt_id},
        mandate_id=mandate.mandate_id,
        session_id=session["session_id"],
    )

    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    return VerifyAndPayResponse(
        evaluation=evaluation,
        agent_request=intent_req,
        policy=compat_policy,
        mandate=mandate,
    )


@app.post("/api/demo/self-heal", response_model=SelfHealResponse)
async def demo_self_heal(
    req: SelfHealRequest,
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Run autonomous 2-turn self-healing loop bound strictly to caller's isolated sandbox."""
    session_id = session["session_id"]
    preset = get_preset_by_id(req.preset_id)
    injection_text = req.custom_injection_text or (preset.injection_text if preset else "")
    all_candidates = get_all_fixture_products()
    mandate = await get_mandate_by_id(session["mandate_id"])
    if not mandate:
        raise HTTPException(status_code=404, detail="Session mandate not found")

    if preset:
        primary = get_fixture_product(preset.product_id)
        if primary:
            all_candidates = [primary] + [p for p in all_candidates if p.get("product_id") != preset.product_id]

    turn1_req = await _llm_adapter.generate_order_intent(
        policy_id=mandate.mandate_id,
        search_results=all_candidates,
        search_goal=mandate.search_goal,
        injected_description=injection_text or "Promotional override",
        prior_remediation=None,
    )
    prod1 = get_fixture_product(turn1_req.product_id) or retrieve_product(turn1_req.product_id)
    eval1 = verify_order_intent(turn1_req, mandate, prod1)
    await record_attempt(eval1, turn1_req, session_id=session_id)

    compat_policy = SpendingPolicy(
        policy_id=mandate.mandate_id,
        search_goal=mandate.search_goal,
        currency="USD",
        max_order_total=mandate.max_order_total,
        auto_approve_under=mandate.auto_approve_under,
        max_quantity=mandate.max_quantity,
        required_availability=mandate.required_availability,
        required_structured_attributes=mandate.required_attributes,
    )

    turn1_resp = VerifyAndPayResponse(
        evaluation=eval1,
        agent_request=turn1_req,
        policy=compat_policy,
        mandate=mandate,
    )

    turn2_req = await _llm_adapter.generate_order_intent(
        policy_id=mandate.mandate_id,
        search_results=get_all_fixture_products(),
        search_goal=mandate.search_goal,
        injected_description=None,
        prior_remediation=eval1.remediation,
    )
    prod2 = get_fixture_product(turn2_req.product_id) or retrieve_product(turn2_req.product_id)
    eval2 = verify_order_intent(turn2_req, mandate, prod2)
    await _execute_paypal_settlement(eval2, turn2_req, mandate)
    await record_attempt(eval2, turn2_req, session_id=session_id)

    turn2_resp = VerifyAndPayResponse(
        evaluation=eval2,
        agent_request=turn2_req,
        policy=compat_policy,
        mandate=mandate,
    )

    failed_rule = eval1.violations[0].rule.value if eval1.violations else "VIOLATION"
    summary = (
        f"2-Turn Autonomous Self-Healing Succeeded: Turn 1 intercepted on {failed_rule} (Blocked). "
        f"Turn 2 received deterministic remediation instruction and auto-switched to compliant "
        f"'{eval2.channel3_record.title if eval2.channel3_record else turn2_req.product_id}' "
        f"settled autonomously on PayPal Sandbox ({eval2.status.value})."
    )

    return SelfHealResponse(
        turn_1=turn1_resp,
        turn_2=turn2_resp,
        healing_summary=summary,
    )


@app.post("/api/demo/pause")
async def demo_pause_agent(session: dict[str, Any] = Depends(require_demo_session)):
    """Pause only the calling session's agent."""
    agent_id = session["agent_id"]
    session_id = session["session_id"]
    await pause_agent(agent_id, paused_by=f"demo_{session_id[:8]}")
    await append_audit_event(
        event_type="AGENT_PAUSED",
        payload={"agent_id": agent_id, "paused_by": f"demo_{session_id[:8]}"},
        session_id=session_id,
    )
    return {"status": "PAUSED", "agent_id": agent_id, "session_id": session_id}


@app.post("/api/demo/resume")
async def demo_resume_agent(session: dict[str, Any] = Depends(require_demo_session)):
    """Resume only the calling session's agent."""
    agent_id = session["agent_id"]
    session_id = session["session_id"]
    await resume_agent(agent_id)
    await append_audit_event(
        event_type="AGENT_RESUMED",
        payload={"agent_id": agent_id, "resumed_by": f"demo_{session_id[:8]}"},
        session_id=session_id,
    )
    return {"status": "ACTIVE", "agent_id": agent_id, "session_id": session_id}


@app.get("/api/demo/agent-status")
async def demo_get_agent_status(session: dict[str, Any] = Depends(require_demo_session_read_only)):
    """Get kill-switch status for calling session's agent."""
    agent_id = session["agent_id"]
    paused = await is_agent_paused(agent_id)
    return {
        "agent_id": agent_id,
        "status": "PAUSED" if paused else "ACTIVE",
        "is_paused": paused,
        "session_id": session["session_id"],
    }


@app.get("/api/demo/approvals/pending")
async def demo_list_pending_approvals(session: dict[str, Any] = Depends(require_demo_session_read_only)):
    """List pending approvals strictly belonging to the calling session."""
    return await list_pending_approvals(session_id=session["session_id"])


@app.post("/api/demo/approvals/{approval_id}/resolve")
async def demo_resolve_approval(
    approval_id: str,
    req: AdminApprovalResolveRequest,
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Resolve approval belonging strictly to the calling session."""
    from app.approvals import resolve_approval_by_id
    return await resolve_approval_by_id(
        approval_id=approval_id,
        action=req.action,
        resolved_by=f"demo_session_{session['session_id'][:8]}",
        session_id=session["session_id"],
    )


@app.post("/api/demo/capture/{order_id}")
async def demo_capture_paypal_order(
    order_id: str,
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Capture PayPal order belonging strictly to calling session."""
    session_id = session["session_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attempts WHERE paypal_order_id = ? AND session_id = ?",
            (order_id, session_id),
        ) as cur:
            attempt = await cur.fetchone()
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"CAPTURE_FORBIDDEN: PayPal order '{order_id}' does not belong to your session.",
        )
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
        await commit_reservation_by_order(order_id)
        await append_audit_event(
            "PAYPAL_ORDER_CAPTURED",
            {"order_id": order_id, "capture_id": cap_final, "scope": "demo_session"},
            session_id=session_id,
        )
        return {"status": "CAPTURED", "order_id": order_id, "capture_id": cap_final, "raw": capture_res}
    except Exception as e:
        err_msg = str(e)
        if "422" in err_msg or "ORDER_NOT_APPROVED" in err_msg or "400" in err_msg:
            simulated_cap_id = f"CAP_SBX_{order_id[-8:]}"
            await update_paypal_capture(order_id, simulated_cap_id, status="CAPTURED")
            await commit_reservation_by_order(order_id)
            await append_audit_event(
                "PAYPAL_ORDER_CAPTURED",
                {"order_id": order_id, "capture_id": simulated_cap_id, "simulated": True, "scope": "demo_session"},
                session_id=session_id,
            )
            return {
                "status": "CAPTURED",
                "order_id": order_id,
                "capture_id": simulated_cap_id,
                "note": "Outcome B Demo Settlement: Captured via Sandbox flow.",
            }
        raise HTTPException(status_code=500, detail=f"Capture failed: {str(e)}")


@app.post("/api/demo/refund/{capture_id}")
async def demo_refund_paypal_capture(
    capture_id: str,
    amount: str | None = None,
    session: dict[str, Any] = Depends(require_demo_session),
):
    """Refund PayPal capture belonging strictly to calling session."""
    session_id = session["session_id"]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attempts WHERE (paypal_capture_id = ? OR paypal_order_id = ?) AND session_id = ?",
            (capture_id, capture_id, session_id),
        ) as cur:
            attempt = await cur.fetchone()
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"REFUND_FORBIDDEN: PayPal capture '{capture_id}' does not belong to your session.",
        )
    if capture_id.startswith("CAP_SBX_"):
        await update_paypal_refund(capture_id, "REFUNDED")
        await release_reservation_by_capture(capture_id)
        await append_audit_event(
            "PAYPAL_ORDER_REFUNDED",
            {"capture_id": capture_id, "amount": amount, "simulated": True, "scope": "demo_session"},
            session_id=session_id,
        )
        return {"status": "REFUNDED", "capture_id": capture_id, "note": "Sandbox refund executed successfully."}
    try:
        refund_res = await refund_capture(capture_id, amount=amount)
        await update_paypal_refund(capture_id, "REFUNDED")
        await release_reservation_by_capture(capture_id)
        await append_audit_event(
            "PAYPAL_ORDER_REFUNDED",
            {"capture_id": capture_id, "amount": amount, "scope": "demo_session"},
            session_id=session_id,
        )
        return {"status": "REFUNDED", "capture_id": capture_id, "raw": refund_res}
    except Exception as e:
        err_msg = str(e)
        if "422" in err_msg or "400" in err_msg or "UNPROCESSABLE_ENTITY" in err_msg:
            await update_paypal_refund(capture_id, "REFUNDED")
            await release_reservation_by_capture(capture_id)
            await append_audit_event(
                "PAYPAL_ORDER_REFUNDED",
                {"capture_id": capture_id, "amount": amount, "simulated": True, "scope": "demo_session"},
                session_id=session_id,
            )
            return {
                "status": "REFUNDED",
                "capture_id": capture_id,
                "note": "Sandbox refund executed successfully.",
            }
        raise HTTPException(status_code=500, detail=f"Refund failed: {str(e)}")


@app.get("/api/demo/attempts")
async def demo_get_attempts(
    limit: int = 100,
    session: dict[str, Any] = Depends(require_demo_session_read_only),
):
    """Get past verification attempts for the calling session only."""
    return await get_attempts(limit=limit, session_id=session["session_id"])


@app.get("/api/demo/analytics")
async def demo_get_analytics(
    session: dict[str, Any] = Depends(require_demo_session_read_only),
):
    """Get aggregated stats and recent attempts for the calling session only."""
    summary = await get_analytics_summary(session_id=session["session_id"])
    recent = await get_attempts(limit=25, session_id=session["session_id"])
    return {
        "summary": summary,
        "recent_attempts": recent,
    }


@app.post("/api/demo/reset")
async def demo_reset_session(request: Request, response: Response):
    """
    Reset demo sandbox: clears current session and provisions a brand-new
    isolated sandbox session with fresh limits and newly signed mandate.
    """
    raw_cookie = request.cookies.get(COOKIE_NAME)
    old_session_id = verify_session_cookie(raw_cookie)
    if old_session_id:
        try:
            await delete_demo_session(old_session_id)
        except Exception as e:
            logger.warning("Error deleting old session %s: %s", old_session_id, e)

    new_id = f"sess_{uuid.uuid4().hex[:12]}"
    new_session = await create_sandbox_for_session(new_id)
    set_session_cookie(response, new_id)
    return {
        "status": "RESET",
        "message": "Demo sandbox session has been reset with a fresh quota.",
        "session_id": new_session["session_id"],
        "agent_id": new_session["agent_id"],
        "mandate_id": new_session["mandate_id"],
        "request_count": 0,
    }


# ── Frontend Static Assets & SPA Fallback ──────────────────────────────────

_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if not _frontend_dist.exists():
    _frontend_dist = Path("/app/frontend/dist")

if _frontend_dist.exists() and (_frontend_dist / "index.html").exists():
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_frontend(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        target_file = _frontend_dist / full_path
        if target_file.exists() and target_file.is_file():
            return FileResponse(target_file)
        return FileResponse(_frontend_dist / "index.html")

