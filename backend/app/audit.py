"""
Intent Gateway — Tamper-Evident Hash-Chained Audit Log Engine.

Guarantees:
1. Cryptographic Hash Chaining: Each event incorporates the SHA-256 hash of its immediate predecessor.
2. Tamper Evident: Any alteration of past event fields, payloads, timestamps, or deletions/reordering
   is deterministically detected by walking the chain.
3. Strict Serialization: Concurrent event appends use SQLite BEGIN IMMEDIATE and memory locks to prevent chain forks.
4. Cryptographic Attestation: The final event hash is signed with Ed25519 for offline portability and verification.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from dataclasses import dataclass

import aiosqlite
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from app.db import DB_PATH
from app.mandate import get_signing_key, get_public_key, get_public_key_hex

logger = logging.getLogger("intent.audit")

# Fixed 64-character hex Genesis Hash for the first block (seq = 1)
GENESIS_HASH: str = "0" * 64

# In-memory lock to guarantee task-level sequential serialization
_APPEND_LOCK = asyncio.Lock()


@dataclass
class AuditEvent:
    seq: int
    event_id: str
    timestamp: str
    mandate_id: Optional[str]
    event_type: str
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str
    session_id: Optional[str] = None


def canonical_event_repr(
    event_id: str,
    timestamp: str,
    mandate_id: Optional[str],
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """
    Produce canonical, deterministic JSON string of event fields for hashing.
    Keys are strictly sorted with compact separators.
    """
    body = {
        "event_id": event_id,
        "event_type": event_type,
        "mandate_id": mandate_id or "",
        "payload": payload,
        "timestamp": timestamp,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def compute_event_hash(
    prev_hash: str,
    event_id: str,
    timestamp: str,
    mandate_id: Optional[str],
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """
    Calculate SHA-256(prev_hash || canonical_json(event fields)).
    Guarantees strict hash-chaining to the predecessor.
    """
    canonical_body = canonical_event_repr(
        event_id=event_id,
        timestamp=timestamp,
        mandate_id=mandate_id,
        event_type=event_type,
        payload=payload,
    )
    raw = f"{prev_hash}{canonical_body}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def append_audit_event(
    event_type: str,
    payload: dict[str, Any],
    mandate_id: Optional[str] = None,
    event_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AuditEvent:
    """
    Append an event to the hash-chained audit log with serialization.
    Acquires an in-memory lock + SQLite BEGIN IMMEDIATE to ensure concurrent writers cannot fork the chain.
    Carries session_id tag when originating from a demo sandbox session.
    """
    async with _APPEND_LOCK:
        now_iso = datetime.now(timezone.utc).isoformat()
        ev_id = event_id or f"ev_{uuid.uuid4().hex[:12]}"
        
        event_payload = dict(payload)
        if session_id and "session_id" not in event_payload:
            event_payload["session_id"] = session_id

        payload_json = json.dumps(event_payload, sort_keys=True)

        async with aiosqlite.connect(DB_PATH, timeout=45.0) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                # Query the latest event to find current head of the chain
                async with db.execute(
                    "SELECT seq, event_hash FROM audit_events ORDER BY seq DESC LIMIT 1"
                ) as cur:
                    last_row = await cur.fetchone()

                if last_row is None:
                    prev_hash = GENESIS_HASH
                else:
                    prev_hash = last_row["event_hash"]

                event_hash = compute_event_hash(
                    prev_hash=prev_hash,
                    event_id=ev_id,
                    timestamp=now_iso,
                    mandate_id=mandate_id,
                    event_type=event_type,
                    payload=event_payload,
                )

                cur = await db.execute(
                    """
                    INSERT INTO audit_events (
                        event_id, timestamp, mandate_id, event_type,
                        payload_json, prev_hash, event_hash, session_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        now_iso,
                        mandate_id,
                        event_type,
                        payload_json,
                        prev_hash,
                        event_hash,
                        session_id,
                    ),
                )
                seq = cur.lastrowid
                await db.commit()

                logger.info(
                    "Audit event appended: seq=%d type=%s hash=%s...",
                    seq,
                    event_type,
                    event_hash[:10],
                )

                return AuditEvent(
                    seq=seq,
                    event_id=ev_id,
                    timestamp=now_iso,
                    mandate_id=mandate_id,
                    event_type=event_type,
                    payload=event_payload,
                    prev_hash=prev_hash,
                    event_hash=event_hash,
                    session_id=session_id,
                )
            except Exception as e:
                await db.rollback()
                logger.error("Failed to append audit event: %s", e)
                raise e


async def verify_audit_chain() -> dict[str, Any]:
    """
    Walk the entire audit log from seq 1 to head.
    Validates:
    - Sequence continuity (1..N with no missing or reordered blocks)
    - Hash continuity (each event's prev_hash matches the preceding event's event_hash)
    - Payload integrity (SHA-256 recomputed matches event_hash via constant-time comparison)

    Returns:
        {valid: bool, events_checked: int, first_broken_seq: Optional[int], message: str}
    """
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM audit_events ORDER BY seq ASC") as cur:
            rows = await cur.fetchall()

        if not rows:
            return {
                "valid": True,
                "events_checked": 0,
                "first_broken_seq": None,
                "message": "Audit log is empty. Chain is intact.",
            }

        expected_prev_hash = GENESIS_HASH
        expected_seq = 1

        for row in rows:
            seq = row["seq"]

            # 1. Sequence numbering must be strictly contiguous
            if seq != expected_seq:
                logger.warning("Audit sequence break detected: expected seq %d, found %d", expected_seq, seq)
                return {
                    "valid": False,
                    "events_checked": expected_seq - 1,
                    "first_broken_seq": seq,
                    "message": f"Sequence break: expected seq {expected_seq}, found {seq}.",
                }

            # 2. Previous hash must match predecessor's event_hash (or GENESIS for seq 1)
            if not hmac.compare_digest(row["prev_hash"], expected_prev_hash):
                logger.warning(
                    "Audit hash continuity broken at seq %d: prev_hash=%s, expected=%s",
                    seq,
                    row["prev_hash"],
                    expected_prev_hash,
                )
                return {
                    "valid": False,
                    "events_checked": expected_seq - 1,
                    "first_broken_seq": seq,
                    "message": f"Hash continuity broken at seq {seq}: prev_hash does not match predecessor hash.",
                }

            # 3. Payload and fields must match recomputed hash
            try:
                payload_dict = json.loads(row["payload_json"])
            except Exception:
                payload_dict = {}

            recomputed_hash = compute_event_hash(
                prev_hash=row["prev_hash"],
                event_id=row["event_id"],
                timestamp=row["timestamp"],
                mandate_id=row["mandate_id"],
                event_type=row["event_type"],
                payload=payload_dict,
            )

            if not hmac.compare_digest(row["event_hash"], recomputed_hash):
                logger.warning(
                    "Audit event tamper detected at seq %d: stored_hash=%s, recomputed=%s",
                    seq,
                    row["event_hash"],
                    recomputed_hash,
                )
                return {
                    "valid": False,
                    "events_checked": expected_seq - 1,
                    "first_broken_seq": seq,
                    "message": f"Tamper detected at seq {seq}: payload or field modification detected.",
                }

            expected_prev_hash = row["event_hash"]
            expected_seq += 1

        return {
            "valid": True,
            "events_checked": len(rows),
            "first_broken_seq": None,
            "final_hash": expected_prev_hash,
            "message": f"Audit chain verified: all {len(rows)} events are authentic and unmodified.",
        }


async def export_audit_chain_signed() -> dict[str, Any]:
    """
    Produce an exportable, Ed25519-signed JSON manifest of the complete audit chain.
    The final hash is signed by the mandate private key for offline cryptographic verification.
    """
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM audit_events ORDER BY seq ASC") as cur:
            rows = await cur.fetchall()

        events_list = []
        final_hash = GENESIS_HASH

        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except Exception:
                payload = {}

            events_list.append({
                "seq": r["seq"],
                "event_id": r["event_id"],
                "timestamp": r["timestamp"],
                "mandate_id": r["mandate_id"],
                "event_type": r["event_type"],
                "payload": payload,
                "prev_hash": r["prev_hash"],
                "event_hash": r["event_hash"],
            })
            final_hash = r["event_hash"]

        signing_key = get_signing_key()
        sig_bytes = signing_key.sign(final_hash.encode("utf-8"))
        sig_hex = sig_bytes.hex()
        pub_hex = get_public_key_hex()

        return {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "genesis_hash": GENESIS_HASH,
            "final_hash": final_hash,
            "signature": sig_hex,
            "public_key": pub_hex,
            "events_count": len(events_list),
            "events": events_list,
        }


def verify_offline_export(export_data: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Offline verification of an exported audit log manifest without requiring a running server or database.
    1. Validates the Ed25519 signature on final_hash using the embedded public key.
    2. Walks the event list from seq 1 to N, verifying genesis hash, hash chaining, and SHA-256 payload integrity.
    """
    try:
        final_hash = export_data.get("final_hash")
        sig_hex = export_data.get("signature")
        pub_hex = export_data.get("public_key")
        events = export_data.get("events", [])
        genesis_hash = export_data.get("genesis_hash", GENESIS_HASH)

        if not final_hash or not sig_hex or not pub_hex:
            return False, "Missing cryptographic fields in export manifest."

        # 1. Verify Ed25519 signature of final_hash
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
            pub_key.verify(bytes.fromhex(sig_hex), final_hash.encode("utf-8"))
        except (InvalidSignature, ValueError) as e:
            return False, f"Signature verification failed: {e}"

        # 2. Walk events
        expected_prev = genesis_hash
        expected_seq = 1

        for ev in events:
            seq = ev.get("seq")
            if seq != expected_seq:
                return False, f"Sequence break: expected {expected_seq}, got {seq}"

            prev_hash = ev.get("prev_hash")
            if not hmac.compare_digest(prev_hash, expected_prev):
                return False, f"Hash continuity broken at seq {seq}: prev_hash does not match predecessor"

            ev_id = ev.get("event_id")
            timestamp = ev.get("timestamp")
            mandate_id = ev.get("mandate_id")
            event_type = ev.get("event_type")
            payload = ev.get("payload", {})
            stored_hash = ev.get("event_hash")

            recomputed = compute_event_hash(
                prev_hash=prev_hash,
                event_id=ev_id,
                timestamp=timestamp,
                mandate_id=mandate_id,
                event_type=event_type,
                payload=payload,
            )

            if not hmac.compare_digest(stored_hash, recomputed):
                return False, f"Tamper detected at seq {seq}: event_hash mismatch"

            expected_prev = stored_hash
            expected_seq += 1

        if not hmac.compare_digest(expected_prev, final_hash):
            return False, "Final event hash does not match attested final_hash"

        return True, None
    except Exception as e:
        return False, f"Verification failed with unexpected error: {e}"


# ── Audit Chain Anchoring in PayPal Orders ─────────────────────────────────

async def get_audit_event_by_hash(event_hash: str) -> Optional[dict[str, Any]]:
    """Look up an audit event record by its SHA-256 event_hash."""
    async with aiosqlite.connect(DB_PATH, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM audit_events WHERE event_hash = ?",
            (event_hash,),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["payload"] = json.loads(d.get("payload_json", "{}"))
            except Exception:
                d["payload"] = {}
            return d


async def verify_order_audit_anchor(
    order_id: str,
    order_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Fetch order from PayPal sandbox API (or use provided data) and confirm that
    its purchase_units[0].custom_id matches an authentic audit event hash in the chain.
    """
    if order_data is None:
        from app.paypal_client import get_order
        try:
            order_data = await get_order(order_id)
        except Exception as e:
            return {
                "valid": False,
                "order_id": order_id,
                "anchored_hash": None,
                "matches_chain": False,
                "error": f"Failed to fetch order from PayPal API: {e}",
            }

    pu_list = order_data.get("purchase_units", [])
    if not pu_list:
        return {
            "valid": False,
            "order_id": order_id,
            "anchored_hash": None,
            "matches_chain": False,
            "error": "PayPal order contains no purchase units",
        }

    custom_id = pu_list[0].get("custom_id", "").strip()
    invoice_id = pu_list[0].get("invoice_id")
    if not custom_id:
        return {
            "valid": False,
            "order_id": order_id,
            "anchored_hash": None,
            "matches_chain": False,
            "error": "PayPal order has no custom_id anchor",
        }

    # Verify that custom_id exists in our cryptographic audit chain
    ev = await get_audit_event_by_hash(custom_id)
    if not ev:
        return {
            "valid": False,
            "order_id": order_id,
            "anchored_hash": custom_id,
            "invoice_id": invoice_id,
            "matches_chain": False,
            "error": f"Anchor mismatch: custom_id '{custom_id}' not found in audit chain",
        }

    return {
        "valid": True,
        "order_id": order_id,
        "anchored_hash": custom_id,
        "invoice_id": invoice_id,
        "matches_chain": True,
        "event_seq": ev.get("seq"),
        "event_type": ev.get("event_type"),
        "event_timestamp": ev.get("timestamp"),
        "attempt_id": ev.get("payload", {}).get("attempt_id"),
    }


