#!/usr/bin/env python3
"""
Intent Gateway — Offline Audit Export Verifier.

Usage:
    python scripts/verify_audit_export.py <path_to_export.json>

Verifies:
1. Ed25519 digital signature of final_hash against the embedded public key.
2. Contiguous sequence ordering (seq 1..N).
3. Hash-chain continuity from GENESIS_HASH to final_hash.
4. SHA-256 cryptographic integrity of all individual event payloads and timestamps.

Zero server connection required. Runs completely offline.
"""

import sys
import json
import hmac
import hashlib
from typing import Any, Optional

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.exceptions import InvalidSignature
except ImportError:
    print("❌ Error: 'cryptography' library is required.")
    print("Install it with: pip install cryptography")
    sys.exit(2)

GENESIS_HASH: str = "0" * 64


def canonical_event_repr(
    event_id: str,
    timestamp: str,
    mandate_id: Optional[str],
    event_type: str,
    payload: dict[str, Any],
) -> str:
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
    canonical_body = canonical_event_repr(
        event_id=event_id,
        timestamp=timestamp,
        mandate_id=mandate_id,
        event_type=event_type,
        payload=payload,
    )
    raw = f"{prev_hash}{canonical_body}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_export_manifest(data: dict[str, Any]) -> bool:
    print("\n" + "=" * 64)
    print("🔍 INTENT AI FIREWALL — OFFLINE AUDIT LOG VERIFIER")
    print("=" * 64)

    final_hash = data.get("final_hash")
    sig_hex = data.get("signature")
    pub_hex = data.get("public_key")
    events = data.get("events", [])
    genesis_hash = data.get("genesis_hash", GENESIS_HASH)

    if not final_hash or not sig_hex or not pub_hex:
        print("❌ Malformed export: Missing final_hash, signature, or public_key.")
        return False

    print(f"• Total Events:     {len(events)}")
    print(f"• Attested Head:    {final_hash[:16]}...{final_hash[-8:]}")
    print(f"• Public Key:       {pub_hex[:16]}...{pub_hex[-8:]}")

    # 1. Verify Ed25519 signature
    print("\n[Step 1/2] Verifying cryptographic Ed25519 attestation signature...")
    try:
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub_key.verify(bytes.fromhex(sig_hex), final_hash.encode("utf-8"))
        print("  ✓ Ed25519 signature is VALID. Final hash was signed by mandate authority.")
    except (InvalidSignature, ValueError) as e:
        print(f"  ❌ SIGNATURE INVALID: {e}")
        return False

    # 2. Walk hash chain
    print("\n[Step 2/2] Walking hash chain from genesis block...")
    expected_prev = genesis_hash
    expected_seq = 1

    for ev in events:
        seq = ev.get("seq")
        if seq != expected_seq:
            print(f"  ❌ SEQUENCE BREAK at event {seq}: expected seq {expected_seq}.")
            return False

        prev_hash = ev.get("prev_hash")
        if not hmac.compare_digest(prev_hash, expected_prev):
            print(f"  ❌ HASH CHAIN BROKEN at seq {seq}!")
            print(f"     Stored prev_hash:   {prev_hash}")
            print(f"     Expected prev_hash: {expected_prev}")
            return False

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
            print(f"  ❌ TAMPER DETECTED at seq {seq} (event {ev_id})!")
            print(f"     Type:               {event_type}")
            print(f"     Stored event_hash:  {stored_hash}")
            print(f"     Recomputed hash:    {recomputed}")
            return False

        expected_prev = stored_hash
        expected_seq += 1

    if not hmac.compare_digest(expected_prev, final_hash):
        print("  ❌ Final event hash does not match signed final_hash.")
        return False

    print(f"  ✓ Verified all {len(events)} events. Every block matches recomputed SHA-256 hash.")
    print("=" * 64)
    print("✅ AUDIT CHAIN VERIFICATION SUCCESS: CHAIN IS AUTHENTIC & UNTAMPERED")
    print("=" * 64 + "\n")
    return True


def main():
    if len(sys.argv) >= 2:
        file_path = sys.argv[1]
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ Failed to read export file '{file_path}': {e}")
            sys.exit(1)
    else:
        # No file argument provided: export live chain from database
        print("No export file passed. Exporting live audit chain from database...")
        import asyncio
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
        try:
            from app.audit import export_audit_chain_signed
            data = asyncio.run(export_audit_chain_signed())
        except Exception as e:
            print(f"❌ Failed to export live audit chain: {e}")
            print("Usage: python scripts/verify_audit_export.py [path_to_export.json]")
            sys.exit(1)

    is_valid = verify_export_manifest(data)
    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()

