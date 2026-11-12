"""Intent Gateway — SQLite persistence for attempt logging and AG Grid analytics."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from app.models import GatewayEvaluationResponse, OrderIntentRequest
from app.mandate import Mandate, MandateStatus, create_demo_mandate, get_signing_key

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """Resolve configured database path with persistent defaults."""
    env_path = os.environ.get("DATABASE_PATH", "").strip()
    if env_path:
        if env_path == ":memory:":
            return Path(":memory:")
        return Path(env_path).resolve()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url:
        if db_url == ":memory:":
            return Path(":memory:")
        if db_url.startswith("sqlite:///"):
            clean = db_url[10:]
            return Path(":memory:") if clean == ":memory:" else Path(clean).resolve()
        elif db_url.startswith("sqlite://"):
            clean = db_url[9:]
            return Path(":memory:") if clean == ":memory:" else Path(clean).resolve()

    # Check settings if available
    try:
        from app.config import get_settings
        settings = get_settings()
        if settings.database_path:
            return Path(":memory:") if settings.database_path == ":memory:" else Path(settings.database_path).resolve()
        if settings.database_url and settings.database_url.startswith("sqlite://"):
            clean = settings.database_url.replace("sqlite:///", "").replace("sqlite://", "")
            return Path(":memory:") if clean == ":memory:" else Path(clean).resolve()
    except Exception:
        pass

    # If running in environment with persistent mount at /var/data
    if Path("/var/data").is_dir():
        return Path("/var/data/intent.db").resolve()

    return (Path(__file__).resolve().parent.parent / "intent.db").resolve()


def get_database_type() -> str:
    """Return database engine type: 'sqlite' or 'postgresql'."""
    db_url = os.environ.get("DATABASE_URL", "").lower().strip()
    if not db_url:
        try:
            from app.config import get_settings
            db_url = (get_settings().database_url or "").lower().strip()
        except Exception:
            pass

    if db_url.startswith(("postgres://", "postgresql://", "psql://")):
        return "postgresql"
    return "sqlite"


def is_persistent_storage() -> bool:
    """Best-effort check if database storage is persistent across restarts."""
    if get_database_type() != "sqlite":
        return True

    path_str = str(get_db_path())
    if path_str == ":memory:" or path_str.endswith(":memory:") or "/tmp" in path_str or "/dev/shm" in path_str:
        return False

    if os.environ.get("RENDER_DISK_NAME") or os.environ.get("PERSISTENT_DISK"):
        return True

    if path_str.startswith("/var/data") or path_str.startswith("/data") or path_str.startswith("/mnt"):
        return True

    if os.environ.get("EPHEMERAL_STORAGE", "").lower() in ("1", "true", "yes"):
        return False

    # Default local dev file path in repository
    return True


class _DatabasePath(os.PathLike):
    """Dynamic Path proxy that resolves get_db_path() at runtime."""

    def __fspath__(self) -> str:
        return str(get_db_path())

    def __str__(self) -> str:
        return str(get_db_path())

    def __repr__(self) -> str:
        return f"_DatabasePath({get_db_path()!r})"

    def __getattr__(self, name: str) -> Any:
        return getattr(get_db_path(), name)

    def __truediv__(self, other: Any) -> Path:
        return get_db_path() / other

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (str, Path, os.PathLike)):
            return str(self) == str(other)
        return False


DB_PATH = _DatabasePath()


async def init_db() -> None:
    """Create database tables and bootstrap demo mandate & agent keys."""
    resolved_path = get_db_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
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

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS mandates (
                mandate_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                mandate_json TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                signature TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_keys (
                agent_id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_reservations (
                reservation_id TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                amount TEXT NOT NULL,
                merchant_domain TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                mandate_id TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                mandate_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_seq ON audit_events(seq)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_mandate ON audit_events(mandate_id)")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                id TEXT PRIMARY KEY,
                attempt_id TEXT NOT NULL,
                mandate_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                merchant_domain TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                subtotal TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'PENDING',
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT,
                resolution_reason TEXT
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_approval_requests_token ON approval_requests(token_hash)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status)")

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                paused_at TEXT,
                paused_by TEXT,
                resumed_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_sessions (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                mandate_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                window_start TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS paypal_anchors (
                order_id TEXT PRIMARY KEY,
                capture_id TEXT,
                attempt_id TEXT NOT NULL,
                mandate_id TEXT,
                anchored_hash TEXT NOT NULL,
                invoice_id TEXT,
                status TEXT NOT NULL DEFAULT 'CREATED',
                created_at TEXT NOT NULL
            )
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_webhooks (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                processed_at TEXT NOT NULL
            )
            """
        )

        # Migration: Ensure all tables have required columns
        async with db.execute("PRAGMA table_info(attempts)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "audit_event_hash" not in columns:
                await db.execute("ALTER TABLE attempts ADD COLUMN audit_event_hash TEXT")
            if "session_id" not in columns:
                await db.execute("ALTER TABLE attempts ADD COLUMN session_id TEXT")

        async with db.execute("PRAGMA table_info(approval_requests)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "session_id" not in columns:
                await db.execute("ALTER TABLE approval_requests ADD COLUMN session_id TEXT")

        async with db.execute("PRAGMA table_info(budget_reservations)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "session_id" not in columns:
                await db.execute("ALTER TABLE budget_reservations ADD COLUMN session_id TEXT")

        async with db.execute("PRAGMA table_info(audit_events)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "session_id" not in columns:
                await db.execute("ALTER TABLE audit_events ADD COLUMN session_id TEXT")

        async with db.execute("PRAGMA table_info(agents)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "session_id" not in columns:
                await db.execute("ALTER TABLE agents ADD COLUMN session_id TEXT")

        async with db.execute("PRAGMA table_info(mandates)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
            if "session_id" not in columns:
                await db.execute("ALTER TABLE mandates ADD COLUMN session_id TEXT")

        await db.commit()

        # Bootstrap demo agent key
        demo_key = os.environ.get("DEMO_AGENT_KEY", "demo_agent_secret_test_key")
        demo_hash = hashlib.sha256(demo_key.encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_keys (agent_id, key_hash, name, created_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("agent_demo_01", demo_hash, "Intent Demo Buyer Agent", now_iso, "ACTIVE"),
        )
        # Register test agent Bob for adversarial multi-agent tests
        bob_hash = hashlib.sha256("bob_different_agent_key".encode("utf-8")).hexdigest()
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_keys (agent_id, key_hash, name, created_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("agent_bob", bob_hash, "Bob Adversarial Test Agent", now_iso, "ACTIVE"),
        )

        # Bootstrap agents table for kill-switch tracking
        await db.execute(
            """
            INSERT OR IGNORE INTO agents (agent_id, name, status, created_at)
            VALUES ('agent_demo_01', 'Intent Demo Buyer Agent', 'ACTIVE', ?)
            """,
            (now_iso,),
        )
        await db.execute(
            """
            INSERT OR IGNORE INTO agents (agent_id, name, status, created_at)
            VALUES ('agent_bob', 'Bob Adversarial Test Agent', 'ACTIVE', ?)
            """,
            (now_iso,),
        )

        # Bootstrap demo mandate
        async with db.execute("SELECT mandate_id FROM mandates WHERE mandate_id = ?", ("demo_mandate_01",)) as cur:
            exists = await cur.fetchone()
            if not exists:
                demo_mandate = create_demo_mandate(get_signing_key())
                await db.execute(
                    """
                    INSERT INTO mandates (mandate_id, owner_id, agent_id, mandate_json, policy_hash, signature, status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        demo_mandate.mandate_id,
                        demo_mandate.owner_id,
                        demo_mandate.agent_id,
                        demo_mandate.model_dump_json(),
                        demo_mandate.policy_hash,
                        demo_mandate.signature,
                        demo_mandate.status.value,
                        demo_mandate.issued_at,
                        demo_mandate.expires_at,
                    ),
                )
                # Also insert legacy alias for backward compatibility with existing tests
                await db.execute(
                    """
                    INSERT OR REPLACE INTO mandates (mandate_id, owner_id, agent_id, mandate_json, policy_hash, signature, status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "laptop_spending_policy_01",
                        demo_mandate.owner_id,
                        demo_mandate.agent_id,
                        demo_mandate.model_dump_json(),
                        demo_mandate.policy_hash,
                        demo_mandate.signature,
                        demo_mandate.status.value,
                        demo_mandate.issued_at,
                        demo_mandate.expires_at,
                    ),
                )

        await db.commit()
    logger.info("Database initialized at %s with Mandates & Agent Keys", DB_PATH)


async def save_mandate(mandate: Mandate, session_id: Optional[str] = None) -> None:
    """Store or update a signed Mandate."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO mandates (
                mandate_id, owner_id, agent_id, mandate_json,
                policy_hash, signature, status, created_at, expires_at, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mandate.mandate_id,
                mandate.owner_id,
                mandate.agent_id,
                mandate.model_dump_json(),
                mandate.policy_hash,
                mandate.signature,
                mandate.status.value if isinstance(mandate.status, MandateStatus) else str(mandate.status),
                mandate.issued_at,
                mandate.expires_at,
                session_id,
            ),
        )
        await db.commit()


async def get_mandate_by_id(mandate_id: str) -> Optional[Mandate]:
    """Retrieve a Mandate by mandate_id (or alias)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT mandate_json, status FROM mandates WHERE mandate_id = ?",
            (mandate_id,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            data = json.loads(row["mandate_json"])
            data["status"] = row["status"]
            return Mandate(**data)


async def revoke_mandate(mandate_id: str) -> bool:
    """Revoke a Mandate by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE mandates SET status = 'REVOKED' WHERE mandate_id = ?",
            (mandate_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def save_agent_key(agent_id: str, raw_key: str, name: str) -> None:
    """Register an agent API key (stored hashed only)."""
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_keys (agent_id, key_hash, name, created_at, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, key_hash, name, now_iso, "ACTIVE"),
        )
        await db.commit()


async def get_agent_id_for_key(raw_key: str) -> Optional[str]:
    """
    Authenticate an agent using constant-time hash comparison.
    Returns agent_id if valid, else None.
    """
    if not raw_key:
        return None
    computed_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT agent_id, key_hash FROM agent_keys WHERE status = 'ACTIVE'") as cur:
            rows = await cur.fetchall()
            for row in rows:
                if hmac.compare_digest(row["key_hash"], computed_hash):
                    return row["agent_id"]
    return None


async def record_attempt(
    evaluation: GatewayEvaluationResponse,
    request: OrderIntentRequest,
    audit_event_hash: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """Save a gateway evaluation attempt to SQLite, linking it to the hash-chained audit log and session sandbox."""
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
                agent_reasoning, audit_event_hash, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                audit_event_hash,
                session_id,
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


async def get_attempts(limit: int = 100, session_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch recent attempts ordered by timestamp desc, optionally isolated by session."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if session_id:
            query = "SELECT * FROM attempts WHERE session_id = ? ORDER BY id DESC LIMIT ?"
            params = (session_id, limit)
        else:
            query = "SELECT * FROM attempts ORDER BY id DESC LIMIT ?"
            params = (limit,)

        async with db.execute(query, params) as cursor:
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

                if item.get("audit_event_hash"):
                    item["short_hash"] = f"{item['audit_event_hash'][:10]}..."
                else:
                    item["short_hash"] = "—"

                results.append(item)
            return results


async def update_paypal_refund(
    capture_id: str,
    status: str = "REFUNDED",
) -> None:
    """Update an attempt when PayPal capture is refunded."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE attempts SET status = ? WHERE paypal_capture_id = ?",
            (status, capture_id),
        )
        await db.commit()


async def get_analytics_summary(session_id: Optional[str] = None) -> dict[str, Any]:
    """Calculate aggregated metrics for dashboard, optionally isolated by session."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        where_clause = " WHERE session_id = ?" if session_id else ""
        params = (session_id,) if session_id else ()

        # Total counts by status
        async with db.execute(f"SELECT status, COUNT(*) as count FROM attempts{where_clause} GROUP BY status", params) as cursor:
            status_counts = {row["status"]: row["count"] for row in await cursor.fetchall()}

        # Total attempts
        total_attempts = sum(status_counts.values())

        # Total dollars prevented (Blocked attempts) and safely captured
        dollars_prevented = 0.0
        dollars_captured = 0.0
        async with db.execute(f"SELECT status, computed_subtotal, unit_price, quantity FROM attempts{where_clause}", params) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                subtotal_val = 0.0
                if r["computed_subtotal"]:
                    try:
                        subtotal_val = float(r["computed_subtotal"])
                    except (ValueError, TypeError):
                        subtotal_val = 0.0
                elif r["unit_price"] and r["quantity"]:
                    try:
                        subtotal_val = float(r["unit_price"]) * float(r["quantity"])
                    except (ValueError, TypeError):
                        subtotal_val = 0.0

                if r["status"] == "BLOCKED":
                    dollars_prevented += subtotal_val
                elif r["status"] in ("CAPTURED", "REFUNDED"):
                    dollars_captured += subtotal_val

        # All violations to calculate rule breakdown
        violations_query = f"SELECT violations_json FROM attempts WHERE violations_json IS NOT NULL"
        if session_id:
            violations_query += " AND session_id = ?"
        async with db.execute(violations_query, params) as cursor:
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
            "dollars_prevented": round(dollars_prevented, 2),
            "dollars_captured": round(dollars_captured, 2),
            "violation_breakdown": rule_breakdown,
        }



def get_db():
    """Return an async context manager for database connection."""
    return aiosqlite.connect(DB_PATH)


# ── Agent Kill Switch State ────────────────────────────────────────────────

async def pause_agent(agent_id: str, paused_by: str = "admin") -> bool:
    """Pause an agent via kill switch, immediately blocking all future activity."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO agents (agent_id, name, status, paused_at, paused_by, created_at)
            VALUES (?, ?, 'PAUSED', ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET status = 'PAUSED', paused_at = ?, paused_by = ?
            """,
            (agent_id, f"Agent {agent_id}", now_iso, paused_by, now_iso, now_iso, paused_by),
        )
        await db.commit()
    logger.warning("Agent '%s' PAUSED by '%s' via kill switch.", agent_id, paused_by)
    return True


async def resume_agent(agent_id: str) -> bool:
    """Resume a previously paused agent."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO agents (agent_id, name, status, resumed_at, created_at)
            VALUES (?, ?, 'ACTIVE', ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET status = 'ACTIVE', resumed_at = ?
            """,
            (agent_id, f"Agent {agent_id}", now_iso, now_iso, now_iso),
        )
        await db.commit()
    logger.info("Agent '%s' RESUMED.", agent_id)
    return True


async def is_agent_paused(agent_id: str) -> bool:
    """Check if an agent is currently paused by the kill switch."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT status FROM agents WHERE agent_id = ?", (agent_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == "PAUSED":
                return True
    return False


async def has_prior_committed_order(mandate_id: str, merchant_domain: str) -> bool:
    """Check if this mandate has previously transacted with merchant_domain (escalation rule check)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT COUNT(*) FROM budget_reservations
            WHERE mandate_id = ? AND merchant_domain = ? AND status = 'COMMITTED'
            """,
            (mandate_id, merchant_domain),
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] > 0:
                return True

        async with db.execute(
            """
            SELECT COUNT(*) FROM attempts
            WHERE policy_id = ? AND merchant_domain = ? AND status = 'CAPTURED'
            """,
            (mandate_id, merchant_domain),
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] > 0:
                return True
    return False


# ── Human Approval Channel Storage ─────────────────────────────────────────

async def save_approval_request(req_data: dict[str, Any]) -> None:
    """Store a pending approval request with hashed single-use token."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO approval_requests (
                id, attempt_id, mandate_id, product_id, merchant_domain, quantity,
                subtotal, currency, status, token_hash, created_at, expires_at, session_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req_data["id"],
                req_data["attempt_id"],
                req_data["mandate_id"],
                req_data["product_id"],
                req_data["merchant_domain"],
                req_data["quantity"],
                req_data["subtotal"],
                req_data.get("currency", "USD"),
                req_data.get("status", "PENDING"),
                req_data["token_hash"],
                req_data["created_at"],
                req_data["expires_at"],
                req_data.get("session_id"),
            ),
        )
        await db.commit()


async def get_approval_by_token_hash(token_hash: str) -> dict[str, Any] | None:
    """Look up an approval request by its token hash."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM approval_requests WHERE token_hash = ?",
            (token_hash,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_approval_by_id(approval_id: str) -> dict[str, Any] | None:
    """Look up an approval request by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM approval_requests WHERE id = ?",
            (approval_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_approval_status(
    approval_id: str,
    status: str,
    resolved_by: str | None = None,
    resolution_reason: str | None = None,
) -> bool:
    """Update approval request status (APPROVED, DENIED, EXPIRED)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE approval_requests
            SET status = ?, resolved_at = ?, resolved_by = ?, resolution_reason = ?
            WHERE id = ?
            """,
            (status, now_iso, resolved_by, resolution_reason, approval_id),
        )
        await db.commit()
    return True


async def list_pending_approvals(
    mandate_id: str | None = None,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """List pending approval requests, optionally filtered by mandate_id or session_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        conditions = ["status = 'PENDING'"]
        params: list[Any] = []
        if mandate_id:
            conditions.append("mandate_id = ?")
            params.append(mandate_id)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where_clause = " AND ".join(conditions)
        query = f"SELECT * FROM approval_requests WHERE {where_clause} ORDER BY created_at DESC"

        async with db.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Demo Sandbox Sessions Storage ──────────────────────────────────────────

async def save_demo_session(session_data: dict[str, Any]) -> None:
    """Save or update demo sandbox session metadata."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO demo_sessions (
                session_id, agent_id, mandate_id, created_at,
                expires_at, last_active_at, request_count, window_start
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_data["session_id"],
                session_data["agent_id"],
                session_data["mandate_id"],
                session_data["created_at"],
                session_data["expires_at"],
                session_data["last_active_at"],
                session_data.get("request_count", 0),
                session_data["window_start"],
            ),
        )
        await db.commit()


async def get_demo_session(session_id: str) -> dict[str, Any] | None:
    """Get demo session by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM demo_sessions WHERE session_id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_demo_session_activity(
    session_id: str,
    request_count: int,
    window_start: str,
) -> None:
    """Update last active timestamp, request count and window start for rate limiting."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE demo_sessions
            SET last_active_at = ?, request_count = ?, window_start = ?
            WHERE session_id = ?
            """,
            (now_iso, request_count, window_start, session_id),
        )
        await db.commit()


async def delete_demo_session(session_id: str) -> None:
    """Delete a demo session and release its budget reservations."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM demo_sessions WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM budget_reservations WHERE session_id = ?", (session_id,))
        await db.commit()


async def cleanup_expired_demo_sessions() -> int:
    """Clean up demo sandbox sessions that have expired."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT session_id, agent_id, mandate_id FROM demo_sessions WHERE expires_at < ?",
            (now_iso,),
        ) as cur:
            expired = await cur.fetchall()

        if not expired:
            return 0

        expired_ids = [r["session_id"] for r in expired]
        placeholders = ",".join("?" for _ in expired_ids)
        await db.execute(
            f"DELETE FROM demo_sessions WHERE session_id IN ({placeholders})",
            tuple(expired_ids),
        )
        await db.commit()
        return len(expired)


# ── PayPal Audit Anchors Persistence ───────────────────────────────────────

async def save_paypal_anchor(
    order_id: str,
    attempt_id: str,
    anchored_hash: str,
    invoice_id: Optional[str] = None,
    capture_id: Optional[str] = None,
    mandate_id: Optional[str] = None,
    status: str = "CREATED",
) -> None:
    """Record a cryptographic anchor binding a PayPal order to an audit chain hash."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO paypal_anchors (
                order_id, capture_id, attempt_id, mandate_id,
                anchored_hash, invoice_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, capture_id, attempt_id, mandate_id, anchored_hash, invoice_id, status, now_iso),
        )
        await db.commit()


async def update_paypal_anchor_capture(
    order_id: str,
    capture_id: str,
    status: str = "CAPTURED",
) -> None:
    """Update anchor record with capture ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE paypal_anchors SET capture_id = ?, status = ? WHERE order_id = ?",
            (capture_id, status, order_id),
        )
        await db.commit()


async def get_paypal_anchors(limit: int = 100) -> list[dict[str, Any]]:
    """Retrieve recent PayPal order anchors."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM paypal_anchors ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_paypal_anchor_by_order(order_id: str) -> Optional[dict[str, Any]]:
    """Look up an anchor record by PayPal order_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM paypal_anchors WHERE order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Idempotent Webhook Processing Persistence ──────────────────────────────

async def is_webhook_processed(event_id: str) -> bool:
    """Check if a PayPal webhook event has already been processed."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM processed_webhooks WHERE event_id = ?",
            (event_id,),
        ) as cur:
            return bool(await cur.fetchone())


async def record_processed_webhook(event_id: str, event_type: str) -> None:
    """Mark a PayPal webhook event as processed."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO processed_webhooks (event_id, event_type, processed_at) VALUES (?, ?, ?)",
            (event_id, event_type, now_iso),
        )
        await db.commit()

