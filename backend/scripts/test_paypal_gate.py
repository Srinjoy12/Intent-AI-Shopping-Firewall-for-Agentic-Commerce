"""
Oct 18 Hard Decision Gate — PayPal Sandbox Capability Test Script.

Tests whether PayPal Sandbox credentials support:
- Outcome A: Synchronous single-call card capture (Advanced Card Processing / Vault)
- Outcome B: Standard 2-step order creation + JS SDK / redirect approval

Run with:
  cd backend && python scripts/test_paypal_gate.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

load_dotenv(backend_dir / ".env")

from app.config import get_settings
from app.paypal_client import (
    _get_access_token,
    create_order,
    create_order_with_card,
    refund_capture,
)


async def run_gate_test():
    settings = get_settings()
    print("=" * 70)
    print("INTENT — PAYPAL SANDBOX HARD GATE DECISION TEST (OCTOBER 18 GATE)")
    print("=" * 70)
    print(f"PayPal Base URL: {settings.paypal_base_url}")
    print(f"Client ID:       {settings.paypal_client_id[:10]}... ({'Set' if settings.paypal_client_id else 'MISSING'})")
    print(f"Client Secret:   {'*' * 8} ({'Set' if settings.paypal_client_secret else 'MISSING'})")
    print("-" * 70)

    if not settings.paypal_client_id or not settings.paypal_client_secret:
        print("\n❌ FAIL: PayPal credentials not configured in backend/.env")
        print("Please copy backend/.env.example to backend/.env and populate PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.")
        sys.exit(1)

    # 1. Test OAuth2 token
    print("\n[Step 1/3] Testing OAuth2 Client Credentials...")
    try:
        token = await _get_access_token()
        print(f"  ✓ Token acquired successfully! Token prefix: {token[:12]}...")
    except Exception as e:
        print(f"  ❌ OAuth2 token error: {e}")
        print("Check that your PayPal Sandbox Client ID and Secret are correct.")
        sys.exit(1)

    # 2. Test Standard Order Creation (Outcome B baseline)
    print("\n[Step 2/3] Testing Standard Order Creation (Outcome B baseline)...")
    try:
        order_b = await create_order(
            reference_id="gate_test_ref_b",
            custom_id="intent_gate_test",
            description="Intent Gate Test - Standard Order",
            item_name="Intent Test Laptop",
            sku="test_sku_16gb",
            unit_amount="10.00",
            currency="USD",
            quantity=1,
        )
        print(f"  ✓ Order created! Order ID: {order_b.get('id')}, Status: {order_b.get('status')}")
    except Exception as e:
        print(f"  ❌ Standard order creation failed: {e}")

    # 3. Test Synchronous Card Processing (Outcome A)
    print("\n[Step 3/3] Testing Synchronous Card Processing (Outcome A)...")
    print("  Using standard PayPal Sandbox test card number (4111 1111 1111 1111)...")
    try:
        order_a = await create_order_with_card(
            reference_id="gate_test_ref_a",
            custom_id="intent_gate_test_card",
            description="Intent Gate Test - Synchronous Card",
            item_name="Intent Test Laptop",
            sku="test_sku_16gb",
            unit_amount="10.00",
            currency="USD",
            quantity=1,
            card_number="4111111111111111",
            card_expiry="2028-12",
        )
        status = order_a.get("status")
        print(f"  Order response status: {status}")

        if status == "COMPLETED":
            print("\n" + "=" * 70)
            print("🎉 VERDICT: OUTCOME A CONFIRMED!")
            print("Advanced Card Processing / Vault is ENABLED in your PayPal Sandbox app.")
            print("Synchronous backend-only capture without buyer popups is fully functional.")
            print("=" * 70)
            # Attempt to refund test charge
            try:
                pu = order_a.get("purchase_units", [])
                if pu:
                    captures = pu[0].get("payments", {}).get("captures", [])
                    if captures:
                        cap_id = captures[0].get("id")
                        print(f"\nCleaning up: Refunding test capture {cap_id}...")
                        ref = await refund_capture(cap_id)
                        print(f"  ✓ Refund status: {ref.get('status')}")
            except Exception as re:
                print(f"  (Refund notice: {re})")
            return
        else:
            print(f"  Order status is {status} (not COMPLETED).")

    except Exception as e:
        print(f"  Notice: Synchronous card attempt returned: {e}")

    print("\n" + "=" * 70)
    print("📋 VERDICT: OUTCOME B (STANDARD 2-STEP FLOW)")
    print("=" * 70)
    print("Advanced Card Processing is not enabled on this Sandbox app.")
    print("The system will use Outcome B: Backend creates the order, and the UI")
    print("triggers approval via standard PayPal flow, then calls /api/paypal/capture.")
    print("\nIf you want Outcome A:")
    print("  1. Log into developer.paypal.com")
    print("  2. Go to Apps & Credentials -> Select your Sandbox App")
    print("  3. Under 'App Feature Options', check 'Advanced Credit and Debit Card Payments'")
    print("  4. Save and re-run this script.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_gate_test())
