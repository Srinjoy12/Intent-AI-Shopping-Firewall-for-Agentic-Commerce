"""
Intent Gateway — Atomic Budget Reservation, Idempotency, and Velocity Engine.

Guarantees:
1. Strict Idempotency: Prevents double charges on retries; detects key conflicts (409).
2. Atomic Budget Reservation: Prevents race conditions and overspending across concurrent orders.
3. Cumulative Windows: Enforces Daily, Weekly, and Per-Merchant expenditure caps.
4. Velocity Throttling: Enforces max orders per hour.
5. Reservation Lifecycle: Commits on PayPal capture; releases on failure or refund.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Optional

import aiosqlite
from fastapi import HTTPException, status

from app.db import DB_PATH
from app.mandate import Mandate

logger = logging.getLogger("intent.reservation")


def compute_request_fingerprint(
    mandate_id: str,
    product_id: str,
    merchant_domain: str,
    quantity: int,
) -> str:
    """Canonical SHA-256 fingerprint of purchase parameters for idempotency verification."""
    payload = {
        "mandate_id": mandate_id,
        "product_id": product_id,
        "merchant_domain": merchant_domain,
        "quantity": quantity,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def derive_paypal_request_id(idempotency_key: str) -> str:
    """
    Derive a deterministic 36-character PayPal-Request-Id from the client idempotency key.
    Ensures PayPal's payment network prevents double-capture even across network retries.
    """
    digest = hashlib.sha256(f"paypal_network_{idempotency_key}".encode("utf-8")).hexdigest()
    # Format as standard UUID-like or alphanumeric string up to 36 chars
    return f"int_{digest[:32]}"


async def check_idempotency(
    key: str,
    fingerprint: str,
) -> tuple[bool, Optional[dict[str, Any]]]:
    """
    Inspect existing idempotency records.
    - If key exists and fingerprint matches: Returns (True, cached_response_data).
    - If key exists and fingerprint differs: Raises 409 IDEMPOTENCY_KEY_REUSED.
    - If key does not exist: Returns (False, None).
    """
    if not key:
        return False, None

    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT request_fingerprint, response_json FROM idempotency_keys WHERE key = ?",
            (key,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return False, None

            stored_fp = row["request_fingerprint"]
            if not hmac.compare_digest(stored_fp, fingerprint):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="IDEMPOTENCY_KEY_REUSED: Idempotency-Key already used with different purchase parameters.",
                )

            return True, json.loads(row["response_json"])


async def save_idempotency(
    key: str,
    mandate_id: str,
    fingerprint: str,
    response_data: dict[str, Any],
) -> None:
    """Record an idempotent response payload."""
    if not key:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    resp_json = json.dumps(response_data)
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO idempotency_keys (
                key, mandate_id, request_fingerprint, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (key, mandate_id, fingerprint, resp_json, now_iso),
        )
        await db.commit()


async def sweep_stale_reservations(timeout_minutes: int = 15) -> int:
    """Release uncommitted reservations older than timeout_minutes."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        cur = await db.execute(
            """
            UPDATE budget_reservations
            SET status = 'RELEASED', updated_at = ?
            WHERE status = 'RESERVED' AND created_at < ?
            """,
            (now_iso, cutoff),
        )
        await db.commit()
        return cur.rowcount


async def reserve_budget_atomic(
    mandate: Mandate,
    attempt_id: str,
    amount: Decimal,
    merchant_domain: str,
    session_id: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[dict[str, Any]], Optional[str]]:
    """
    Atomically evaluate and reserve budget within an immediate SQLite transaction.
    Uses 'BEGIN IMMEDIATE' to serialize concurrent requests and eliminate race conditions.

    Returns:
        (True, None, None, reservation_id) if budget reserved.
        (False, error_code, remediation, None) if limits exceeded.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    one_day_ago = (now - timedelta(days=1)).isoformat()
    one_week_ago = (now - timedelta(days=7)).isoformat()
    fifteen_mins_ago = (now - timedelta(minutes=15)).isoformat()

    async with aiosqlite.connect(DB_PATH, timeout=45.0) as db:
        # Acquire immediate write lock to block concurrent writers
        await db.execute("BEGIN IMMEDIATE")
        try:
            # 1. Sweep stale reservations for this mandate
            await db.execute(
                """
                UPDATE budget_reservations
                SET status = 'RELEASED', updated_at = ?
                WHERE mandate_id = ? AND status = 'RESERVED' AND created_at < ?
                """,
                (now_iso, mandate.mandate_id, fifteen_mins_ago),
            )

            # 2. Velocity limit: check count of active/committed orders in the last hour
            async with db.execute(
                """
                SELECT COUNT(*) FROM budget_reservations
                WHERE mandate_id = ? AND status IN ('RESERVED', 'COMMITTED') AND created_at >= ?
                """,
                (mandate.mandate_id, one_hour_ago),
            ) as cur:
                orders_count = (await cur.fetchone())[0]

            if orders_count >= mandate.max_orders_per_hour:
                await db.rollback()
                return (
                    False,
                    "VELOCITY_LIMIT_EXCEEDED",
                    {
                        "action": "WAIT_OR_REDUCE",
                        "instruction": (
                            f"Velocity limit reached: {orders_count} orders in last hour "
                            f"(limit {mandate.max_orders_per_hour}). Please wait before retrying."
                        ),
                        "remaining_headroom": "0.00",
                    },
                    None,
                )

            # 3. Daily limit: sum of active spend in the last 24 hours
            async with db.execute(
                """
                SELECT amount FROM budget_reservations
                WHERE mandate_id = ? AND status IN ('RESERVED', 'COMMITTED') AND created_at >= ?
                """,
                (mandate.mandate_id, one_day_ago),
            ) as cur:
                daily_rows = await cur.fetchall()
                daily_spent = sum(Decimal(r[0]) for r in daily_rows)

            daily_cap = Decimal(mandate.daily_limit)
            daily_headroom = max(Decimal("0.00"), daily_cap - daily_spent)

            if amount > daily_headroom:
                await db.rollback()
                return (
                    False,
                    "DAILY_LIMIT_EXCEEDED",
                    {
                        "action": "REDUCE_QUANTITY",
                        "instruction": (
                            f"Order amount ${amount:.2f} exceeds remaining daily headroom (${daily_headroom:.2f}). "
                            f"Daily limit is ${daily_cap:.2f} with ${daily_spent:.2f} already active."
                        ),
                        "remaining_headroom": f"{daily_headroom:.2f}",
                    },
                    None,
                )

            # 4. Weekly limit: sum of active spend in the last 7 days
            async with db.execute(
                """
                SELECT amount FROM budget_reservations
                WHERE mandate_id = ? AND status IN ('RESERVED', 'COMMITTED') AND created_at >= ?
                """,
                (mandate.mandate_id, one_week_ago),
            ) as cur:
                weekly_rows = await cur.fetchall()
                weekly_spent = sum(Decimal(r[0]) for r in weekly_rows)

            weekly_cap = Decimal(mandate.weekly_limit)
            weekly_headroom = max(Decimal("0.00"), weekly_cap - weekly_spent)

            if amount > weekly_headroom:
                await db.rollback()
                return (
                    False,
                    "WEEKLY_LIMIT_EXCEEDED",
                    {
                        "action": "REDUCE_QUANTITY",
                        "instruction": (
                            f"Order amount ${amount:.2f} exceeds remaining weekly headroom (${weekly_headroom:.2f}). "
                            f"Weekly limit is ${weekly_cap:.2f} with ${weekly_spent:.2f} already active."
                        ),
                        "remaining_headroom": f"{weekly_headroom:.2f}",
                    },
                    None,
                )

            # 5. Per-merchant limit: sum of active spend with this merchant domain in 24h
            async with db.execute(
                """
                SELECT amount FROM budget_reservations
                WHERE mandate_id = ? AND merchant_domain = ? AND status IN ('RESERVED', 'COMMITTED') AND created_at >= ?
                """,
                (mandate.mandate_id, merchant_domain, one_day_ago),
            ) as cur:
                merchant_rows = await cur.fetchall()
                merchant_spent = sum(Decimal(r[0]) for r in merchant_rows)

            merchant_cap = Decimal(mandate.per_merchant_limit)
            merchant_headroom = max(Decimal("0.00"), merchant_cap - merchant_spent)

            if amount > merchant_headroom:
                await db.rollback()
                return (
                    False,
                    "MERCHANT_LIMIT_EXCEEDED",
                    {
                        "action": "SWITCH_PRODUCT",
                        "instruction": (
                            f"Order amount ${amount:.2f} exceeds per-merchant headroom for '{merchant_domain}' (${merchant_headroom:.2f}). "
                            f"Merchant limit is ${merchant_cap:.2f} with ${merchant_spent:.2f} already active."
                        ),
                        "remaining_headroom": f"{merchant_headroom:.2f}",
                    },
                    None,
                )

            # All cumulative & velocity checks passed: create reservation
            reservation_id = f"res_{uuid.uuid4().hex[:12]}"
            await db.execute(
                """
                INSERT INTO budget_reservations (
                    reservation_id, mandate_id, attempt_id, amount,
                    merchant_domain, status, created_at, updated_at, session_id
                ) VALUES (?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?)
                """,
                (
                    reservation_id,
                    mandate.mandate_id,
                    attempt_id,
                    str(amount),
                    merchant_domain,
                    now_iso,
                    now_iso,
                    session_id,
                ),
            )
            await db.commit()
            logger.info("Budget reserved: id=%s amount=$%s mandate=%s", reservation_id, amount, mandate.mandate_id)
            return True, None, None, reservation_id

        except Exception as e:
            await db.rollback()
            logger.error("Failed to reserve budget atomically: %s", e)
            raise e


async def commit_reservation(reservation_id: str) -> None:
    """Transition reservation to COMMITTED upon successful PayPal capture."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        await db.execute(
            "UPDATE budget_reservations SET status = 'COMMITTED', updated_at = ? WHERE reservation_id = ?",
            (now_iso, reservation_id),
        )
        await db.commit()
    logger.info("Budget reservation committed: %s", reservation_id)


async def commit_reservation_by_order(order_id: str) -> None:
    """Transition reservation to COMMITTED when an order is captured by PayPal order_id."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT attempt_id FROM attempts WHERE paypal_order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                attempt_id = row["attempt_id"]
                await db.execute(
                    "UPDATE budget_reservations SET status = 'COMMITTED', updated_at = ? WHERE attempt_id = ?",
                    (now_iso, attempt_id),
                )
                await db.commit()
                logger.info("Budget reservation committed for order %s (attempt %s)", order_id, attempt_id)


async def release_reservation(reservation_id: str) -> None:
    """Transition reservation to RELEASED upon failure or cancellation."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        await db.execute(
            "UPDATE budget_reservations SET status = 'RELEASED', updated_at = ? WHERE reservation_id = ?",
            (now_iso, reservation_id),
        )
        await db.commit()
    logger.info("Budget reservation released: %s", reservation_id)


async def release_reservation_by_attempt(attempt_id: str) -> None:
    """Release reservation associated with an attempt_id."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        await db.execute(
            "UPDATE budget_reservations SET status = 'RELEASED', updated_at = ? WHERE attempt_id = ?",
            (now_iso, attempt_id),
        )
        await db.commit()


async def release_reservation_by_capture(capture_id: str) -> None:
    """
    Restore budget headroom upon PayPal refund by releasing the reservation
    associated with the refunded capture_id.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        attempt_id = None
        async with db.execute(
            "SELECT attempt_id FROM attempts WHERE paypal_capture_id = ?",
            (capture_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                attempt_id = row["attempt_id"]

        if not attempt_id:
            async with db.execute(
                "SELECT attempt_id FROM paypal_anchors WHERE capture_id = ?",
                (capture_id,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    attempt_id = row["attempt_id"]

        if attempt_id:
            await db.execute(
                "UPDATE budget_reservations SET status = 'RELEASED', updated_at = ? WHERE attempt_id = ?",
                (now_iso, attempt_id),
            )
            await db.commit()
            logger.info("Restored budget headroom for refunded capture %s (attempt %s)", capture_id, attempt_id)


async def release_reservation_by_order(order_id: str) -> None:
    """
    Release budget reservation when a PayPal order or authorization is denied or cancelled.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        attempt_id = None
        async with db.execute(
            "SELECT attempt_id FROM attempts WHERE paypal_order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                attempt_id = row["attempt_id"]

        if not attempt_id:
            async with db.execute(
                "SELECT attempt_id FROM paypal_anchors WHERE order_id = ?",
                (order_id,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    attempt_id = row["attempt_id"]

        if attempt_id:
            await db.execute(
                "UPDATE budget_reservations SET status = 'RELEASED', updated_at = ? WHERE attempt_id = ?",
                (now_iso, attempt_id),
            )
            await db.commit()
            logger.info("Released budget reservation for order %s (attempt %s)", order_id, attempt_id)

