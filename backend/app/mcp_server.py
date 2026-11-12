"""
Intent AI Gateway — Official Model Context Protocol (MCP) Server.

Architecture & Security:
- Runs as a separate process communicating via stdio or SSE.
- Uses the official Python MCP SDK (mcp>=1.0.0).
- Exposes strictly four client-facing shopping tools:
    1. search_products
    2. submit_order_intent
    3. get_mandate_status
    4. get_order_status
- Strictly FORBIDS admin actions (no mandate creation/edit, no approval, no refunds, no pause).
- Authenticates to the Intent Gateway over HTTP using its configured AGENT_API_KEY.
- Returns machine-readable structured remediation JSON on block so clients can self-heal.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Optional
import httpx

from mcp.server.mcpserver import MCPServer

logger = logging.getLogger("intent.mcp")

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")
AGENT_API_KEY = os.environ.get("DEMO_AGENT_KEY", "demo_agent_secret_test_key")

# Initialize official MCPServer
mcp_server = MCPServer("intent-shopping-firewall")


async def _gateway_request(
    method: str,
    path: str,
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Helper to dispatch HTTP calls to the gateway, using ASGI transport in tests or HTTP in production."""
    import sys
    req_headers = {
        "X-Agent-Key": AGENT_API_KEY,
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)

    # Use in-process ASGI app for test isolation and instantaneous test execution
    if "pytest" in sys.modules:
        from app.main import app
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(method, path, json=json_data, params=params, headers=req_headers)
            try:
                return resp.json()
            except Exception:
                return {"status_code": resp.status_code, "text": resp.text}

    url = f"{GATEWAY_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, json=json_data, params=params, headers=req_headers)
            if resp.status_code == 404:
                return {"error": "NOT_FOUND", "status_code": 404, "detail": resp.text}
            return resp.json()
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.error("Failed to connect to Intent Gateway at %s: %s", url, e)
        return {"error": "GATEWAY_UNAVAILABLE", "detail": str(e)}


# ── Core MCP Tool Implementations ──────────────────────────────────────────

async def mcp_search_products(query: str = "laptop", limit: int = 5) -> dict[str, Any]:
    """
    Search product catalog via Channel3 or verified fallback fixtures.
    Read-only tool: safe against financial alteration.
    """
    return await _gateway_request("GET", "/api/products/search", params={"q": query, "limit": limit})


async def mcp_submit_order_intent(
    mandate_id: str,
    product_id: str,
    merchant_domain: str,
    quantity: int = 1,
) -> dict[str, Any]:
    """
    Submit a purchase intent to the Intent Deterministic Gateway.
    Untrusted agent can ONLY submit: mandate_id, product_id, domain, and quantity.
    Returns structured remediation JSON if blocked so the agent can self-heal.
    """
    payload = {
        "mandate_id": mandate_id,
        "product_id": product_id,
        "merchant_domain": merchant_domain,
        "quantity": quantity,
        "agent_reasoning": "Submitted via Intent MCP Tool Client",
    }
    res = await _gateway_request("POST", "/api/verify-and-pay", json_data=payload)

    # If the response wraps an evaluation, unwrap for convenient client consumption
    if "evaluation" in res:
        eval_data = res["evaluation"]
        return {
            "status": eval_data.get("status"),
            "attempt_id": eval_data.get("attempt_id"),
            "computed_subtotal": eval_data.get("computed_subtotal"),
            "violations": [v.get("rule") for v in eval_data.get("violations", [])],
            "remediation": eval_data.get("remediation"),
            "paypal_capture_id": eval_data.get("paypal_capture_id") or res.get("paypal_capture_id"),
            "paypal_order_id": eval_data.get("paypal_order_id") or res.get("paypal_order_id"),
            "message": "Order verified and processed" if eval_data.get("status") != "BLOCKED" else "Order blocked by firewall",
        }
    return res


async def mcp_get_mandate_status(mandate_id: str) -> dict[str, Any]:
    """
    Retrieve spending limits and cryptographic status for a signed mandate.
    Read-only tool: agents cannot alter policy parameters.
    """
    return await _gateway_request("GET", f"/api/mandates/{mandate_id}")


async def mcp_get_order_status(attempt_id: str) -> dict[str, Any]:
    """
    Query historical attempt status, violation audit reasons, or PayPal settlement confirmation.
    """
    attempts_data = await _gateway_request("GET", "/api/attempts")
    if isinstance(attempts_data, list):
        for att in attempts_data:
            if att.get("attempt_id") == attempt_id:
                return att
    return {"error": "ATTEMPT_NOT_FOUND", "attempt_id": attempt_id}


# ── Register Tools on MCPServer ────────────────────────────────────────────

@mcp_server.tool(name="search_products", description="Search 100M+ real merchant products via Channel3.")
async def tool_search_products(query: str, limit: int = 5) -> str:
    res = await mcp_search_products(query, limit)
    return json.dumps(res, indent=2)


@mcp_server.tool(name="submit_order_intent", description="Submit an order intent to Intent Deterministic Firewall. Returns remediation JSON if blocked.")
async def tool_submit_order_intent(mandate_id: str, product_id: str, merchant_domain: str, quantity: int = 1) -> str:
    res = await mcp_submit_order_intent(mandate_id, product_id, merchant_domain, quantity)
    return json.dumps(res, indent=2)


@mcp_server.tool(name="get_mandate_status", description="Inspect verified spending limits and validity for a mandate.")
async def tool_get_mandate_status(mandate_id: str) -> str:
    res = await mcp_get_mandate_status(mandate_id)
    return json.dumps(res, indent=2)


@mcp_server.tool(name="get_order_status", description="Query order verification or PayPal settlement status.")
async def tool_get_order_status(attempt_id: str) -> str:
    res = await mcp_get_order_status(attempt_id)
    return json.dumps(res, indent=2)


def list_mcp_tool_names() -> list[str]:
    """Return list of tool names exposed by this MCP server."""
    return ["search_products", "submit_order_intent", "get_mandate_status", "get_order_status"]


if __name__ == "__main__":
    print(f"Starting Intent MCP Server on stdio (connecting to Gateway at {GATEWAY_URL})...", file=sys.stderr)
    mcp_server.run()
