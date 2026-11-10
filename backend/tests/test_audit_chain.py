"""
Adversarial Pytest Suite for Task 3:
Tamper-Evident Hash-Chained Audit Log.

Covers:
1. A valid chain verifies end-to-end.
2. Modifying any field of a past event is detected, with the correct first_broken_seq.
3. Deleting an event in the middle is detected.
4. Reordering events is detected.
5. 50 concurrent appends keep the chain valid (strict serialization, zero forks).
6. An exported file verifies offline, and a modified export fails.
"""

import os
import json
import asyncio
import pytest
import aiosqlite
import httpx
from httpx import ASGITransport

from app.main import app
from app.db import DB_PATH, init_db
from app.config import get_settings
from app.audit import (
    GENESIS_HASH,
    append_audit_event,
    verify_audit_chain,
    export_audit_chain_signed,
    verify_offline_export,
)


@pytest.fixture(autouse=True, scope="session")
def setup_test_environment():
    os.environ["ADMIN_API_KEY"] = "admin_super_secret_test_key"
    os.environ["DEMO_AGENT_KEY"] = "demo_agent_secret_test_key"
    get_settings().admin_api_key = "admin_super_secret_test_key"
    app.state.limiter.enabled = False
    asyncio.run(init_db())


@pytest.fixture(autouse=True)
def clean_audit_events():
    """Ensure clean audit_events table before each test."""
    async def _clean():
        await init_db()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM audit_events")
            await db.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_events'")
            await db.commit()
    asyncio.run(_clean())


@pytest.mark.asyncio
async def test_valid_audit_chain_verifies():
    """A valid sequential chain verifies completely."""
    # Append 5 sequential events across lifecycle
    ev1 = await append_audit_event("MANDATE_CREATED", {"mandate_id": "man_audit_01", "max_total": "1000.00"}, mandate_id="man_audit_01")
    assert ev1.seq == 1
    assert ev1.prev_hash == GENESIS_HASH

    ev2 = await append_audit_event("REQUEST_RECEIVED", {"product_id": "pPB4LGu", "quantity": 1}, mandate_id="man_audit_01")
    assert ev2.seq == 2
    assert ev2.prev_hash == ev1.event_hash

    ev3 = await append_audit_event("EVALUATION_RULE_RESULT", {"status": "VERIFIED_READY_FOR_PAYPAL"}, mandate_id="man_audit_01")
    assert ev3.seq == 3
    assert ev3.prev_hash == ev2.event_hash

    ev4 = await append_audit_event("RESERVATION_CREATED", {"amount": "899.99"}, mandate_id="man_audit_01")
    ev5 = await append_audit_event("PAYPAL_ORDER_CAPTURED", {"capture_id": "CAP_TEST_123"}, mandate_id="man_audit_01")

    # Verify via Python API
    result = await verify_audit_chain()
    assert result["valid"] is True
    assert result["events_checked"] == 5
    assert result["first_broken_seq"] is None

    # Verify via HTTP API
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/audit/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["events_checked"] == 5
        assert data["first_broken_seq"] is None


@pytest.mark.asyncio
async def test_tampered_field_detected():
    """Modifying any field of a past event is detected, returning the exact first_broken_seq."""
    for i in range(1, 6):
        await append_audit_event("REQUEST_RECEIVED", {"order_num": i, "amount": f"{i * 100}.00"})

    # Tamper with event seq 3 in SQLite directly (bypassing hash calculation)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE audit_events SET payload_json = ? WHERE seq = 3",
            (json.dumps({"order_num": 3, "amount": "99999.00"}),),
        )
        await db.commit()

    # Verification must fail and point to seq 3
    result = await verify_audit_chain()
    assert result["valid"] is False
    assert result["first_broken_seq"] == 3

    # Verification via HTTP API must return the same
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/audit/verify")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["first_broken_seq"] == 3


@pytest.mark.asyncio
async def test_deleted_event_detected():
    """Deleting an event in the middle is detected as a broken hash chain."""
    for i in range(1, 6):
        await append_audit_event("ACTION_EVENT", {"step": i})

    # Delete event seq 3
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM audit_events WHERE seq = 3")
        await db.commit()

    # The chain at seq 4 will now point to seq 3's hash, but the predecessor in DB is seq 2
    result = await verify_audit_chain()
    assert result["valid"] is False
    assert result["first_broken_seq"] in (3, 4)


@pytest.mark.asyncio
async def test_reordered_events_detected():
    """Reordering events breaks hash continuity and is detected."""
    for i in range(1, 5):
        await append_audit_event("STEP_EVENT", {"step": i})

    # Swap payload and event_id of seq 2 and seq 3
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM audit_events WHERE seq = 2") as c:
            r2 = dict(await c.fetchone())
        async with db.execute("SELECT * FROM audit_events WHERE seq = 3") as c:
            r3 = dict(await c.fetchone())

        # Swap event_ids and payloads without updating hashes
        await db.execute("UPDATE audit_events SET payload_json = ? WHERE seq = 2", (r3["payload_json"],))
        await db.execute("UPDATE audit_events SET payload_json = ? WHERE seq = 3", (r2["payload_json"],))
        await db.commit()

    result = await verify_audit_chain()
    assert result["valid"] is False
    assert result["first_broken_seq"] == 2


@pytest.mark.asyncio
async def test_50_concurrent_appends_keep_chain_valid():
    """50 concurrent appends must be serialized so the chain does not fork."""
    async def add_event(idx: int):
        return await append_audit_event(
            "CONCURRENT_EVENT",
            {"worker_idx": idx, "payload_data": f"token_{idx}"},
            mandate_id="man_concurrent",
        )

    # Dispatch 50 concurrent writes
    events = await asyncio.gather(*[add_event(i) for i in range(50)])
    assert len(events) == 50

    # Ensure all seq numbers from 1 to 50 exist without duplicates
    seqs = [e.seq for e in events]
    assert sorted(seqs) == list(range(1, 51))

    # Verify the entire chain
    result = await verify_audit_chain()
    assert result["valid"] is True
    assert result["events_checked"] == 50
    assert result["first_broken_seq"] is None


@pytest.mark.asyncio
async def test_offline_export_verification():
    """An exported chain verifies offline via Ed25519 signature + hash walk; tampered export fails."""
    for i in range(1, 6):
        await append_audit_event("EXPORT_TEST_EVENT", {"item": i, "val": i * 10})

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admin_headers = {"X-Admin-Key": "admin_super_secret_test_key"}
        resp = await client.get("/api/audit/export", headers=admin_headers)
        assert resp.status_code == 200
        export_data = resp.json()

        assert "events" in export_data
        assert "final_hash" in export_data
        assert "signature" in export_data
        assert "public_key" in export_data
        assert len(export_data["events"]) == 5

        # 1. Offline verification passes on unmodified export
        is_valid, err = verify_offline_export(export_data)
        assert is_valid is True
        assert err is None

        # 2. Tampering with event payload in export fails offline verification
        tampered_data = json.loads(json.dumps(export_data))
        tampered_data["events"][2]["payload"]["val"] = 9999
        is_v_tamper, err_tamper = verify_offline_export(tampered_data)
        assert is_v_tamper is False
        assert "Tamper detected" in err_tamper or "hash mismatch" in err_tamper.lower()

        # 3. Tampering with the final signature fails offline verification
        tampered_sig = json.loads(json.dumps(export_data))
        tampered_sig["signature"] = "00" * 64
        is_v_sig, err_sig = verify_offline_export(tampered_sig)
        assert is_v_sig is False
        assert "Signature" in err_sig or "signature" in err_sig.lower()
