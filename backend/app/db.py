"""Intent Gateway — SQLite persistence for attempt logging and AG Grid analytics."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.models import GatewayEvaluationResponse, OrderIntentRequest

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "intent.db"


async def init_db() -> None:
    """Create the attempts table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                attempt_id TEXT NOT NULL UNIQUE,
                policy_id TEXT NOT NULL,
                status TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_title TEXT,
                merchant_domain TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price TEXT,
                computed_subtotal TEXT,
                violations_json TEXT,
                remediation_json TEXT,
                paypal_order_id TEXT,
                paypal_capture_id TEXT,
                agent_reasoning TEXT
            )
            """
        )
        await db.commit()
    logger.info("Database initialized at %s", DB_PATH)


async def record_attempt(
    evaluation: GatewayEvaluationResponse,
    request: OrderIntentRequest,
) -> None:
    """Save a gateway evaluation attempt to SQLite."""
    now_iso = datetime.now(timezone.utc).isoformat()
    violations_json = json.dumps([v.model_dump() for v in evaluation.violations])
    remediation_json = json.dumps(evaluation.remediation.model_dump()) if evaluation.remediation else None
    
    product_title = evaluation.channel3_record.title if evaluation.channel3_record else ""
    unit_price = evaluation.channel3_record.unit_price if evaluation.channel3_record else None

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO attempts (
                timestamp, attempt_id, policy_id, status,
                product_id, product_title, merchant_domain, quantity,
                unit_price, computed_subtotal, violations_json,
                remediation_json, paypal_order_id, paypal_capture_id,
                agent_reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso,
                evaluation.attempt_id,
                evaluation.policy_id,
                evaluation.status.value,
                request.product_id,
                product_title,
                request.merchant_domain,
                request.quantity,
                unit_price,
                evaluation.computed_subtotal,
                violations_json,
                remediation_json,
                evaluation.paypal_order_id,
                evaluation.paypal_capture_id,
                request.agent_reasoning,
            ),
        )
        await db.commit()


async def update_paypal_order(
    attempt_id: str,
    paypal_order_id: str,
    status: str | None = None,
) -> None:
    """Update an attempt with PayPal order details."""
    async with aiosqlite.connect(DB_PATH) as db:
        if status:
            await db.execute(
                "UPDATE attempts SET paypal_order_id = ?, status = ? WHERE attempt_id = ?",
                (paypal_order_id, status, attempt_id),
            )
        else:
            await db.execute(
                "UPDATE attempts SET paypal_order_id = ? WHERE attempt_id = ?",
                (paypal_order_id, attempt_id),
            )
        await db.commit()


async def update_paypal_capture(
    order_id: str,
    paypal_capture_id: str,
    status: str = "CAPTURED",
) -> None:
    """Update an attempt when PayPal order is captured."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE attempts SET paypal_capture_id = ?, status = ? WHERE paypal_order_id = ?",
            (paypal_capture_id, status, order_id),
        )
        await db.commit()


async def get_attempts(limit: int = 100) -> list[dict[str, Any]]:
    """Fetch recent attempts ordered by timestamp desc."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM attempts ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("violations_json"):
                    try:
                        item["violations"] = json.loads(item["violations_json"])
                    except Exception:
                        item["violations"] = []
                else:
                    item["violations"] = []
                if item.get("remediation_json"):
                    try:
                        item["remediation"] = json.loads(item["remediation_json"])
                    except Exception:
                        item["remediation"] = None
                else:
                    item["remediation"] = None
                results.append(item)
            return results


async def get_analytics_summary() -> dict[str, Any]:
    """Calculate aggregated metrics for AG Studio dashboard."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total counts by status
        async with db.execute("SELECT status, COUNT(*) as count FROM attempts GROUP BY status") as cursor:
            status_counts = {row["status"]: row["count"] for row in await cursor.fetchall()}

        # Total attempts
        total_attempts = sum(status_counts.values())

        # All violations to calculate rule breakdown
        async with db.execute("SELECT violations_json FROM attempts WHERE violations_json IS NOT NULL") as cursor:
            all_violations_rows = await cursor.fetchall()

        rule_breakdown: dict[str, int] = {}
        for row in all_violations_rows:
            raw = row["violations_json"]
            if raw:
                try:
                    v_list = json.loads(raw)
                    for v in v_list:
                        rule = v.get("rule", "OTHER")
                        rule_breakdown[rule] = rule_breakdown.get(rule, 0) + 1
                except Exception:
                    pass

        return {
            "total_attempts": total_attempts,
            "blocked_count": status_counts.get("BLOCKED", 0),
            "verified_count": status_counts.get("VERIFIED_READY_FOR_PAYPAL", 0),
            "captured_count": status_counts.get("CAPTURED", 0),
            "refunded_count": status_counts.get("REFUNDED", 0),
            "violation_breakdown": rule_breakdown,
        }
