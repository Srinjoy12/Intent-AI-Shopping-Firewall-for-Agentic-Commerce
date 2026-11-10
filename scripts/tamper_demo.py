#!/usr/bin/env python3
"""
Intent Gateway — Dev Tamper Injection Demo Tool.

Usage:
    python scripts/tamper_demo.py [tamper | restore | status] [--seq <number>]

Description:
    Demonstrates Intent's cryptographic tamper-evidence in video walkthroughs and live demos.
    Directly modifies a historical event payload inside SQLite without updating the hash chain.
    The web console and GET /api/audit/verify will immediately flag the exact corrupted block.
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "backend" / "intent.db"
BACKUP_PATH = Path(__file__).resolve().parent / ".tamper_backup.json"


def get_connection():
    if not DB_PATH.exists():
        print(f"❌ Database not found at: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def show_status():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT seq, event_id, event_type, prev_hash, event_hash, payload_json FROM audit_events ORDER BY seq ASC")
    rows = cur.fetchall()
    print("\n" + "=" * 70)
    print("📋 AUDIT EVENTS CHAIN STATUS")
    print("=" * 70)
    if not rows:
        print("  (No events recorded yet. Run a purchase intent first!)")
        return
    for r in rows:
        print(f"[{r['seq']:03d}] {r['event_type']:<22} hash={r['event_hash'][:12]}... prev={r['prev_hash'][:12]}...")
        print(f"      payload: {r['payload_json'][:65]}...")
    print("=" * 70 + "\n")


def inject_tamper(target_seq: int = None):
    conn = get_connection()
    cur = conn.cursor()

    if target_seq is None:
        # Pick the second event or first available event with payload
        cur.execute("SELECT seq, payload_json FROM audit_events ORDER BY seq ASC LIMIT 2")
        rows = cur.fetchall()
        if not rows:
            print("❌ No events to tamper with. Submit a purchase intent in the app first!")
            return
        target_seq = rows[-1]["seq"]

    cur.execute("SELECT seq, event_id, event_type, payload_json, event_hash FROM audit_events WHERE seq = ?", (target_seq,))
    row = cur.fetchone()
    if not row:
        print(f"❌ Event seq {target_seq} not found.")
        return

    orig_payload = row["payload_json"]
    # Save backup for clean restore
    backup_data = {
        "seq": target_seq,
        "payload_json": orig_payload,
    }
    with open(BACKUP_PATH, "w", encoding="utf-8") as f:
        json.dump(backup_data, f)

    try:
        payload_dict = json.loads(orig_payload)
    except Exception:
        payload_dict = {}

    # Mutate payload
    payload_dict["__TAMPERED__"] = True
    payload_dict["hacked_amount"] = "$999,999.00"
    payload_dict["tamper_note"] = "Unauthorized direct database edit by attacker"
    new_payload_json = json.dumps(payload_dict)

    cur.execute("UPDATE audit_events SET payload_json = ? WHERE seq = ?", (new_payload_json, target_seq))
    conn.commit()

    print("\n" + "!" * 70)
    print(f"🚨 TAMPER INJECTED AT EVENT SEQ {target_seq} ({row['event_type']})!")
    print("!" * 70)
    print(f"• Event ID:          {row['event_id']}")
    print(f"• Stored Hash:        {row['event_hash']}")
    print("• Action:            Modified payload directly in SQLite without updating hash chain.")
    print("• Next Steps for Demo:")
    print("   1. Open the Intent web UI (http://localhost:5173)")
    print("   2. Click the 'Verify Chain' button in the audit ledger")
    print(f"   3. Notice the UI turns RED and flags block #{target_seq} as tampered!")
    print("   4. Run `python scripts/tamper_demo.py restore` to restore the original state.")
    print("!" * 70 + "\n")


def restore():
    if not BACKUP_PATH.exists():
        print("❌ No tamper backup found to restore.")
        return

    with open(BACKUP_PATH, "r", encoding="utf-8") as f:
        backup = json.load(f)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE audit_events SET payload_json = ? WHERE seq = ?", (backup["payload_json"], backup["seq"]))
    conn.commit()
    BACKUP_PATH.unlink(missing_ok=True)
    print(f"\n✅ Restored event seq {backup['seq']} to original state.")
    print("Audit chain is now clean and valid.\n")


def main():
    parser = argparse.ArgumentParser(description="Intent Audit Log Tamper Demo Script")
    parser.add_argument("action", nargs="?", default="tamper", choices=["tamper", "restore", "status"], help="Action to execute")
    parser.add_argument("--seq", type=int, default=None, help="Specific event sequence number to tamper with")
    args = parser.parse_args()

    if args.action == "tamper":
        inject_tamper(args.seq)
    elif args.action == "restore":
        restore()
    elif args.action == "status":
        show_status()


if __name__ == "__main__":
    main()

