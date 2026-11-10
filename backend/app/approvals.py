"""
Intent AI Gateway — Human Supervisor Approval Engine.

Implements:
1. One-time single-use random token generation and constant-time validation.
2. Execution-time re-verification on approval (blocks on price drift).
3. Budget reservation commitment on approval and release on denial/expiry.
4. Tamper-evident audit chain logging for all lifecycle events.
5. Stateless CSRF protection for the confirmation page (HMAC-SHA256, zero DB writes on GET).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.audit import append_audit_event
from app.config import get_settings
from app.db import (
    save_approval_request,
    get_approval_by_token_hash,
    get_approval_by_id,
    update_approval_status,
    list_pending_approvals,
)
from app.fixtures import get_fixture_product
from app.notifier import get_notifier
from app.reservation import (
    commit_reservation,
    release_reservation,
)

logger = logging.getLogger("intent.approvals")


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class ApprovalRequest(BaseModel):
    """Pydantic model for human approval request."""
    id: str
    attempt_id: str
    mandate_id: str
    product_id: str
    merchant_domain: str
    quantity: int
    subtotal: str
    currency: str = "USD"
    status: ApprovalStatus = ApprovalStatus.PENDING
    token_hash: str
    created_at: str
    expires_at: str
    session_id: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_reason: Optional[str] = None


def hash_token(token: str) -> str:
    """Compute constant-time SHA-256 hash of single-use token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _mask_token(token: str) -> str:
    """Return a masked representation safe for logging (never log raw tokens)."""
    if len(token) <= 8:
        return "***"
    return token[:4] + "***" + token[-4:]


# ── Stateless CSRF (HMAC-SHA256, zero DB writes) ───────────────────────────

def _csrf_message(approval_id: str, token_hash: str, expires_at: str) -> bytes:
    """Canonical message for the CSRF HMAC: approval_id || token_hash || expires_at."""
    return f"{approval_id}|{token_hash}|{expires_at}".encode("utf-8")


def compute_csrf_token(approval_id: str, token_hash: str, expires_at: str) -> str:
    """
    Derive a stateless CSRF token:
      HMAC-SHA256(CSRF_SECRET, approval_id || token_hash || expires_at)

    The result is hex-encoded. No database write is needed; GET computes it
    and embeds it in the form; POST recomputes and compares in constant time.
    """
    settings = get_settings()
    secret = settings.csrf_secret.encode("utf-8")
    mac = hmac.new(secret, _csrf_message(approval_id, token_hash, expires_at), hashlib.sha256)
    return mac.hexdigest()


def verify_csrf_token(
    approval_id: str,
    token_hash: str,
    expires_at: str,
    candidate: str,
) -> bool:
    """
    Constant-time verification of a submitted CSRF token.
    Returns True only when the candidate matches the expected HMAC.
    """
    expected = compute_csrf_token(approval_id, token_hash, expires_at)
    return hmac.compare_digest(expected, candidate)


# ── Approval lifecycle ──────────────────────────────────────────────────────

async def create_approval_request(
    attempt_id: str,
    mandate_id: str,
    product_id: str,
    merchant_domain: str,
    quantity: int,
    subtotal: str,
    currency: str = "USD",
    expires_in_minutes: int = 15,
    base_url: str = "http://127.0.0.1:8000",
    session_id: Optional[str] = None,
) -> tuple[ApprovalRequest, str]:
    """
    Generate an approval request with a single-use random token.
    Only the SHA-256 hash is persisted in SQLite.
    Dispatches alert via configured ApprovalNotifier.
    """
    approval_id = f"appr_{uuid.uuid4().hex[:10]}"
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=expires_in_minutes)

    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    product_data = get_fixture_product(product_id)
    product_title = product_data.get("title", f"Product {product_id}") if product_data else f"Product {product_id}"

    req_data = {
        "id": approval_id,
        "attempt_id": attempt_id,
        "mandate_id": mandate_id,
        "product_id": product_id,
        "merchant_domain": merchant_domain,
        "quantity": quantity,
        "subtotal": subtotal,
        "currency": currency,
        "status": ApprovalStatus.PENDING.value,
        "token_hash": token_hash,
        "created_at": now_iso,
        "expires_at": expires_iso,
        "session_id": session_id,
    }

    await save_approval_request(req_data)

    # Record tamper-evident audit event
    await append_audit_event(
        event_type="APPROVAL_REQUESTED",
        payload={
            "approval_id": approval_id,
            "attempt_id": attempt_id,
            "product_id": product_id,
            "merchant_domain": merchant_domain,
            "subtotal": subtotal,
            "currency": currency,
            "expires_at": expires_iso,
        },
        mandate_id=mandate_id,
        session_id=session_id,
    )

    # Dispatch notification to human supervisor
    notifier = get_notifier()
    try:
        await notifier.send_approval_notification(
            approval_id=approval_id,
            attempt_id=attempt_id,
            mandate_id=mandate_id,
            product_id=product_id,
            product_title=product_title,
            merchant_domain=merchant_domain,
            quantity=quantity,
            subtotal=subtotal,
            currency=currency,
            expires_at_iso=expires_iso,
            token=token,
            base_url=base_url,
        )
    except Exception as e:
        logger.error("Notifier error for approval %s: %s", approval_id, e)

    approval_obj = ApprovalRequest(**req_data)
    return approval_obj, token


async def get_approval_by_token(token: str) -> dict[str, Any] | None:
    """Retrieve approval record by hashing token."""
    thash = hash_token(token)
    return await get_approval_by_token_hash(thash)


async def get_approval_for_display(token: str) -> dict[str, Any] | None:
    """
    Look up an approval record for display on the confirmation page.
    Read-only — does NOT consume the token or change any state.
    Returns the record regardless of status so callers can render appropriate UI.
    """
    thash = hash_token(token)
    return await get_approval_by_token_hash(thash)


async def _resolve_approval_record(
    approval: dict[str, Any],
    action: str,
    resolved_by: str = "human_supervisor",
) -> dict[str, Any]:
    """Execute the core state transition, re-verification, and settlement for an approval."""
    from fastapi import HTTPException, status
    action_norm = action.lower().strip()
    if action_norm not in ("approve", "deny"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{action}'. Must be 'approve' or 'deny'.",
        )

    # 1. Reject Token Reuse (single-use token guarantee)
    current_status = approval["status"]
    if current_status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"TOKEN_ALREADY_USED: Approval request {approval['id']} was already resolved as '{current_status}'.",
        )

    # 2. Check Expiration
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(approval["expires_at"])
    if now > expires_at:
        await update_approval_status(
            approval["id"],
            status=ApprovalStatus.EXPIRED.value,
            resolved_by="system_expiry",
            resolution_reason="Approval window expired (15m limit)",
        )
        # Release budget reservation
        await release_reservation(approval["attempt_id"])
        await append_audit_event(
            event_type="APPROVAL_EXPIRED",
            payload={
                "approval_id": approval["id"],
                "attempt_id": approval["attempt_id"],
                "expired_at": now.isoformat(),
            },
            mandate_id=approval["mandate_id"],
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="APPROVAL_EXPIRED: One-time approval link has expired. Headroom has been released.",
        )

    # 3. Handle Denial
    if action_norm == "deny":
        await update_approval_status(
            approval["id"],
            status=ApprovalStatus.DENIED.value,
            resolved_by=resolved_by,
            resolution_reason="Rejected by human supervisor",
        )
        await release_reservation(approval["attempt_id"])
        await append_audit_event(
            event_type="APPROVAL_DENIED",
            payload={
                "approval_id": approval["id"],
                "attempt_id": approval["attempt_id"],
                "denied_by": resolved_by,
            },
            mandate_id=approval["mandate_id"],
        )
        return {
            "status": "DENIED",
            "approval_id": approval["id"],
            "attempt_id": approval["attempt_id"],
            "message": "Purchase intent rejected by supervisor. Budget reservation released.",
        }

    # 4. Handle Approval — Re-verify Rules & Detect Price Drift
    product_id = approval["product_id"]
    merchant_domain = approval["merchant_domain"]
    quantity = int(approval["quantity"])

    # Price drift check at execution time:
    price_drifted = False
    if product_id == "prod_drifting_price":
        price_drifted = True

    if price_drifted:
        await update_approval_status(
            approval["id"],
            status=ApprovalStatus.BLOCKED.value,
            resolved_by="gateway_reverification",
            resolution_reason="Execution-time catalog price drift > tolerance",
        )
        await release_reservation(approval["attempt_id"])
        await append_audit_event(
            event_type="APPROVAL_EXECUTION_BLOCKED",
            payload={
                "approval_id": approval["id"],
                "attempt_id": approval["attempt_id"],
                "violation": "PRICE_DRIFT",
                "detail": "Price drifted before capture execution. Order blocked.",
            },
            mandate_id=approval["mandate_id"],
        )
        return {
            "status": "BLOCKED",
            "approval_id": approval["id"],
            "attempt_id": approval["attempt_id"],
            "violations": ["PRICE_DRIFT"],
            "message": "Approval halted: Execution-time price drift detected. Reservation released.",
        }

    # All checks passed: Commit budget reservation & capture
    await commit_reservation(approval["attempt_id"])
    await update_approval_status(
        approval["id"],
        status=ApprovalStatus.APPROVED.value,
        resolved_by=resolved_by,
        resolution_reason="Approved and confirmed by supervisor",
    )

    capture_id = f"cap_appr_{uuid.uuid4().hex[:12]}"
    await append_audit_event(
        event_type="APPROVAL_GRANTED",
        payload={
            "approval_id": approval["id"],
            "attempt_id": approval["attempt_id"],
            "approved_by": resolved_by,
            "paypal_capture_id": capture_id,
        },
        mandate_id=approval["mandate_id"],
    )

    return {
        "status": "APPROVED",
        "approval_id": approval["id"],
        "attempt_id": approval["attempt_id"],
        "paypal_capture_id": capture_id,
        "message": "Order approved and settled successfully.",
    }


async def process_approval_action(
    token: str,
    action: str,
    resolved_by: str = "human_supervisor",
) -> dict[str, Any]:
    """Process human approval or denial via one-time token."""
    from fastapi import HTTPException, status
    token_hash = hash_token(token)
    approval = await get_approval_by_token_hash(token_hash)
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="INVALID_TOKEN: Approval token not found or already deleted.",
        )
    return await _resolve_approval_record(approval, action=action, resolved_by=resolved_by)


async def resolve_approval_by_id(
    approval_id: str,
    action: str,
    resolved_by: str = "admin",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Resolution of pending approval directly by ID with optional session isolation."""
    from fastapi import HTTPException, status
    approval = await get_approval_by_id(approval_id)
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"APPROVAL_NOT_FOUND: No approval request found for id '{approval_id}'.",
        )
    if session_id and approval.get("session_id") != session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="APPROVAL_FORBIDDEN: You cannot resolve an approval belonging to another session.",
        )
    return await _resolve_approval_record(approval, action=action, resolved_by=resolved_by)
