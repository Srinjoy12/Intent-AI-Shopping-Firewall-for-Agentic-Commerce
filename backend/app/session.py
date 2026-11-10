"""
Intent AI Gateway — Demo Sandbox and Session Management Engine.

Implements:
1. Per-visitor isolated sandboxes in demo mode (unique session, agent_id, Ed25519-signed mandate, budget).
2. Signed HttpOnly Lax session cookies (tamper-proof via HMAC-SHA256).
3. Session rate limiting (max 30 requests per session per hour).
4. Automatic 2-hour TTL expiration and background sweep.
5. Strict multi-tenant session isolation across mandates, attempts, approvals, and actions.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import aiosqlite
from fastapi import Request, Response, HTTPException, status

from app.config import get_settings
from app.db import (
    DB_PATH,
    save_demo_session,
    get_demo_session,
    update_demo_session_activity,
    delete_demo_session,
    cleanup_expired_demo_sessions,
    save_mandate,
)
from app.mandate import get_signing_key, sign_mandate, Mandate

logger = logging.getLogger("intent.session")

COOKIE_NAME = "intent_session"


def sign_session_id(session_id: str) -> str:
    """Sign a session_id with HMAC-SHA256 using SESSION_SECRET."""
    settings = get_settings()
    secret = settings.session_secret.encode("utf-8")
    sig = hmac.new(secret, session_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{session_id}.{sig}"


def verify_session_cookie(cookie_val: Optional[str]) -> Optional[str]:
    """Verify signed session cookie value. Returns session_id if valid, None if invalid or tampered."""
    if not cookie_val or "." not in cookie_val:
        return None
    try:
        session_id, sig = cookie_val.split(".", 1)
        settings = get_settings()
        secret = settings.session_secret.encode("utf-8")
        expected_sig = hmac.new(secret, session_id.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        if hmac.compare_digest(expected_sig, sig):
            return session_id
    except Exception:
        pass
    return None


def create_session_mandate(session_id: str, agent_id: str, mandate_id: str, expires_at_iso: str) -> Mandate:
    """Construct and cryptographically sign a dedicated Mandate for this demo sandbox session."""
    now = datetime.now(timezone.utc)
    mandate_data = {
        "mandate_id": mandate_id,
        "owner_id": f"user_{session_id}",
        "agent_id": agent_id,
        "max_order_total": "1200.00",
        "auto_approve_under": "1000.00",
        "max_quantity": 1,
        "required_attributes": {
            "ram": "16GB",
            "storage": "512GB",
        },
        "allowed_domains": [
            "staples.com",
            "bestbuy.com",
            "newegg.com",
        ],
        "required_availability": "InStock",
        "daily_limit": "2500.00",
        "weekly_limit": "7500.00",
        "per_merchant_limit": "1500.00",
        "max_orders_per_hour": 10,
        "issued_at": now.isoformat(),
        "expires_at": expires_at_iso,
        "nonce": f"nonce_{session_id}",
    }
    return sign_mandate(mandate_data, get_signing_key())


async def create_sandbox_for_session(session_id: str) -> dict[str, Any]:
    """
    Initialize an isolated demo sandbox environment:
    - Dedicated session_id
    - Dedicated agent_id with ACTIVE status
    - Dedicated Ed25519-signed mandate stored in SQLite
    - Internal agent key registered
    - Expiration set to 2 hours
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)
    now_iso = now.isoformat()
    expires_iso = expires_at.isoformat()

    agent_id = f"agent_demo_{session_id[-8:]}"
    mandate_id = f"mandate_demo_{session_id[-8:]}"

    # 1. Create and store signed mandate
    mandate = create_session_mandate(session_id, agent_id, mandate_id, expires_iso)
    await save_mandate(mandate, session_id=session_id)

    # 2. Register agent and agent key in DB
    agent_raw_key = f"key_{session_id}"
    agent_key_hash = hashlib.sha256(agent_raw_key.encode("utf-8")).hexdigest()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agents (agent_id, name, status, created_at, session_id)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            """,
            (agent_id, f"Demo Buyer ({session_id[:8]})", now_iso, session_id),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_keys (agent_id, key_hash, name, created_at, status)
            VALUES (?, ?, ?, ?, 'ACTIVE')
            """,
            (agent_id, agent_key_hash, f"Demo Key ({session_id[:8]})", now_iso),
        )
        await db.commit()

    # 3. Store demo session
    session_data = {
        "session_id": session_id,
        "agent_id": agent_id,
        "mandate_id": mandate_id,
        "created_at": now_iso,
        "expires_at": expires_iso,
        "last_active_at": now_iso,
        "request_count": 0,
        "window_start": now_iso,
        "internal_agent_key": agent_raw_key,
    }
    await save_demo_session(session_data)
    logger.info("Created demo sandbox session: %s (agent=%s, mandate=%s)", session_id, agent_id, mandate_id)
    return session_data


def set_session_cookie(response: Response, session_id: str) -> None:
    """Set signed HttpOnly, SameSite=Lax cookie on HTTP response."""
    settings = get_settings()
    signed_val = sign_session_id(session_id)
    # Secure flag in production HTTPS; False in local dev/demo
    is_secure = (settings.app_mode == "admin" and not getattr(settings, "debug", True))
    response.set_cookie(
        key=COOKIE_NAME,
        value=signed_val,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


async def get_or_create_demo_session(request: Request, response: Response) -> dict[str, Any]:
    """
    Retrieve existing valid session or provision a new isolated sandbox session.
    If the session is expired, cleans it up and raises HTTP 410 Gone.
    """
    raw_cookie = request.cookies.get(COOKIE_NAME)
    session_id = verify_session_cookie(raw_cookie)

    if session_id:
        session_data = await get_demo_session(session_id)
        if session_data:
            # Check expiry
            now = datetime.now(timezone.utc)
            try:
                expires_at = datetime.fromisoformat(session_data["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except Exception:
                expires_at = now - timedelta(seconds=1)

            if now >= expires_at:
                logger.warning("Sandbox session %s is expired; deleting and rejecting", session_id)
                await delete_demo_session(session_id)
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="SANDBOX_EXPIRED: Demo sandbox session has expired. Reload page for a fresh sandbox.",
                )

            return session_data
        else:
            # Cookie was signed but session not in DB (possibly already cleaned up or expired)
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="SANDBOX_EXPIRED: Demo sandbox session has expired. Reload page for a fresh sandbox.",
            )

    # First-time visit: generate a new isolated sandbox
    new_id = f"sess_{uuid.uuid4().hex[:12]}"
    new_session = await create_sandbox_for_session(new_id)
    set_session_cookie(response, new_id)
    return new_session


async def enforce_session_rate_limit(session_data: dict[str, Any]) -> None:
    """
    Enforce per-session rate limit (default: 30 requests per hour).
    Different sessions have distinct rate limit windows and counters.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    session_id = session_data["session_id"]
    current_count = session_data.get("request_count", 0)
    window_start_str = session_data.get("window_start")

    try:
        window_start = datetime.fromisoformat(window_start_str) if window_start_str else now
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
    except Exception:
        window_start = now

    # Reset hourly window if elapsed
    if (now - window_start).total_seconds() >= 3600:
        new_count = 1
        new_window_start = now.isoformat()
    else:
        if current_count >= settings.session_rate_limit_per_hour:
            logger.warning(
                "Session %s exceeded rate limit: %d/%d reqs/hr",
                session_id,
                current_count,
                settings.session_rate_limit_per_hour,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Per-session rate limit exceeded (maximum {settings.session_rate_limit_per_hour} requests per hour).",
            )
        new_count = current_count + 1
        new_window_start = window_start.isoformat()

    await update_demo_session_activity(session_id, new_count, new_window_start)
    session_data["request_count"] = new_count
    session_data["window_start"] = new_window_start


async def require_demo_session(request: Request, response: Response) -> dict[str, Any]:
    """FastAPI dependency for all /api/demo/* routes."""
    session_data = await get_or_create_demo_session(request, response)
    await enforce_session_rate_limit(session_data)
    return session_data
