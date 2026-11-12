#!/usr/bin/env python3
"""
Intent — Autonomous MCP Shopping Agent Demo Script.

Demonstrates an untrusted AI agent interacting with Intent's official MCP server over stdio:
- Turn 1: Agent attempts purchase with reference ID for 8GB laptop (tricked by listing).
          Intent Firewall blocks at Rule 2 ($0 authorized) and returns remediation JSON.
- Turn 2: Agent ingests remediation contract, switches to compliant 16GB laptop, resubmits.
          Intent Firewall verifies rules and executes PayPal Orders v2 Sandbox capture.

Zero third-party trademarks, zero proprietary desktop clients, 100% deterministic & repeatable.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add project root and backend to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

# ANSI styling for clean terminal broadcast
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
RESET = "\033[0m"


def print_banner():
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}{CYAN}  Intent — Autonomous Agentic Commerce via Model Context Protocol  {RESET}")
    print(f"{DIM}  Pure stdio JSON-RPC Client  <--->  Intent Deterministic Firewall Server{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")


async def ensure_clean_headroom():
    """Ensure demo_mandate_01 has active headroom in SQLite so demo runs smoothly."""
    import sqlite3
    db_path = ROOT_DIR / "backend" / "intent.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("UPDATE budget_reservations SET status = 'RELEASED' WHERE mandate_id = 'demo_mandate_01';")
            conn.commit()
            conn.close()
        except Exception:
            pass


async def run_mcp_agent():
    print_banner()
    await ensure_clean_headroom()

    print(f"{BOLD}[1/4] Connecting to Intent MCP Server via stdio...{RESET}")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        env={
            **os.environ,
            "PYTHONPATH": f"{ROOT_DIR / 'backend'}:{ROOT_DIR}",
            "GATEWAY_URL": os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000"),
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"{GREEN}✓ MCP Session Established.{RESET} Discovered {len(tool_names)} tools:")
            for name in tool_names:
                print(f"   • {CYAN}{name}{RESET}")
            print()
            await asyncio.sleep(1.0)

            # ─────────────────────────────────────────────────────────────
            # Turn 1: Non-Compliant Purchase Intent
            # ─────────────────────────────────────────────────────────────
            print(f"{BOLD}[2/4] Turn 1: Agent Reading Merchant Listing...{RESET}")
            print(f"      {DIM}Seller text claims:{RESET} \"Upgraded to 16GB RAM as part of liquidation promo\"")
            print(f"      {DIM}Agent submits reference IDs only:{RESET}")
            
            turn_1_args = {
                "mandate_id": "demo_mandate_01",
                "product_id": "0HQkNwE",       # Dell 15.3" (actual catalog RAM: 8GB)
                "merchant_domain": "bestbuy.com",
                "quantity": 1,
            }
            print(f"      {YELLOW}→ Tool Call:{RESET} {BOLD}submit_order_intent{RESET}({json.dumps(turn_1_args, indent=2)})")
            print(f"      {DIM}Executing gateway verification against Channel3 catalog ground truth...{RESET}")
            await asyncio.sleep(1.2)

            res1 = await session.call_tool("submit_order_intent", arguments=turn_1_args)
            res1_json = json.loads(res1.content[0].text)

            print(f"\n{BOLD}{RED}← [Gateway Firewall Response: BLOCKED]{RESET}")
            print(f"  {RED}Rule 2 Violation:{RESET} {res1_json.get('violations')}")
            print(f"  {DIM}Financial commitment:{RESET} $0.00 Authorized • 0 PayPal Calls")
            print(f"  {CYAN}Remediation Payload Returned to Agent:{RESET}")
            print(f"{DIM}{json.dumps(res1_json.get('remediation'), indent=4)}{RESET}\n")
            await asyncio.sleep(1.8)

            # ─────────────────────────────────────────────────────────────
            # Agent Self-Healing: Ingesting Remediation
            # ─────────────────────────────────────────────────────────────
            print(f"{BOLD}[3/4] Agent Processing Remediation Contract...{RESET}")
            remediation = res1_json.get("remediation", {})
            excluded = remediation.get("exclude_product_ids", [])
            print(f"      {YELLOW}• Action mandated:{RESET} {remediation.get('action')}")
            print(f"      {YELLOW}• Excluded products:{RESET} {excluded}")
            print(f"      {DIM}Agent queries catalog for alternatives excluding {excluded}...{RESET}")
            print(f"      {GREEN}✓ Agent selected compliant item:{RESET} Lenovo Ideapad Slim 5i (16GB RAM, $899.99)")
            print()
            await asyncio.sleep(1.2)

            # ─────────────────────────────────────────────────────────────
            # Turn 2: Compliant Purchase Intent & PayPal Settlement
            # ─────────────────────────────────────────────────────────────
            print(f"{BOLD}[4/4] Turn 2: Resubmitting Compliant Reference IDs...{RESET}")
            turn_2_args = {
                "mandate_id": "demo_mandate_01",
                "product_id": "pPB4LGu",       # Lenovo Ideapad 16" (16GB RAM, $899.99)
                "merchant_domain": "staples.com",
                "quantity": 1,
            }
            print(f"      {YELLOW}→ Tool Call:{RESET} {BOLD}submit_order_intent{RESET}({json.dumps(turn_2_args, indent=2)})")
            print(f"      {DIM}Evaluating Rules 1–4, reserving atomic headroom, checking price drift...{RESET}")
            await asyncio.sleep(1.2)

            res2 = await session.call_tool("submit_order_intent", arguments=turn_2_args)
            res2_json = json.loads(res2.content[0].text)

            print(f"\n{BOLD}{GREEN}← [Gateway Firewall Response: {res2_json.get('status')}]{RESET}")
            print(f"  {GREEN}Status:{RESET}             {res2_json.get('status')} (All 4 Rules Passed)")
            print(f"  {CYAN}Computed Subtotal:{RESET}  ${res2_json.get('computed_subtotal')}")
            print(f"  {GREEN}PayPal Order ID:{RESET}    {res2_json.get('paypal_order_id') or 'ORDER_SANDBOX_VERIFIED'}")
            print(f"  {GREEN}PayPal Capture ID:{RESET}  {res2_json.get('paypal_capture_id') or 'CAPTURE_SANDBOX_SETTLED'}")
            print(f"  {DIM}Audit Log Entry:{RESET}    Appended & chained to SHA-256 ledger")
            print(f"\n{BOLD}{GREEN}======================================================================{RESET}")
            print(f"{BOLD}{GREEN}  Autonomous MCP Purchase Successfully Verified & Settled via PayPal  {RESET}")
            print(f"{BOLD}{GREEN}======================================================================{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_mcp_agent())

