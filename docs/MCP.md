# Intent MCP Server Integration Guide

The **Intent Model Context Protocol (MCP) Server** (`backend/app/mcp_server.py`) allows AI agents (e.g., Claude Desktop, Cursor, bespoke autonomous agents) to safely discover products and express purchase intent through the Intent shopping firewall.

---

## 🛡️ Security Architecture & Trust Boundary

```
+------------------------------------+
|            AI Agent                |
|     (e.g., Claude Desktop)         |
+-----------------+------------------+
                  | MCP Protocol (stdio / JSON-RPC)
                  v
+------------------------------------+
|         Intent MCP Server          |
|    - Holds Agent API Key only      |
|    - Isolated process              |
+-----------------+------------------+
                  | HTTP + Ed25519 Mandate
                  v
+------------------------------------+
|       Intent Gateway Engine        |
|  - Cryptographic Mandate Check     |
|  - Real Catalog Price/Spec Verify  |
|  - Atomic Budget Reservation       |
|  - Human Approval Channel          |
|  - Tamper-Evident Hash Audit Chain |
+-----------------+------------------+
                  | PayPal Sandbox API
                  v
         [PayPal Payments v2]
```

### Key Security Principles:
1. **Reference IDs Only:** Agents cannot supply prices, titles, specs, policy rules, or payment fields. Agents only specify `mandate_id`, `product_id`, `merchant_domain`, and `quantity`.
2. **Zero Admin Exposure:** The MCP server strictly exposes zero administrative tools. It **cannot** create, modify, or revoke mandates, approve or deny requests, pause agents, or issue refunds.
3. **Structured Remediation for Self-Healing:** When an order intent violates a mandate rule (e.g., spec mismatch, out of stock, budget exceeded), the MCP server returns the complete deterministic `remediation` JSON so the AI agent can intelligently self-correct without human intervention unless human escalation is required.

---

## 🛠️ Available MCP Tools

| Tool Name | Arguments | Permissions | Description |
|-----------|-----------|-------------|-------------|
| `search_products` | `query: str`, `limit: int = 5` | Agent | Read-only product search across verified Channel3 merchant catalogs. |
| `submit_order_intent` | `mandate_id: str`, `product_id: str`, `merchant_domain: str`, `quantity: int = 1` | Agent | Submits purchase intent to the firewall engine for deterministic verification and atomic budget reservation. |
| `get_mandate_status` | `mandate_id: str` | Agent | Fetches active limits, expiration, and remaining budget headroom for the specified mandate. |
| `get_order_status` | `attempt_id: str` | Agent | Checks the lifecycle state, PayPal order ID, capture status, or human approval status of a purchase attempt. |

---

## ⚙️ Client Configuration Snippet

### Claude Desktop (`claude_desktop_config.json`)

To connect Claude Desktop to Intent, add the following to your `claude_desktop_config.json` (located at `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "intent-firewall": {
      "command": "/Users/srinjoyroy/Documents/Paypal AI hackathon/backend/venv/bin/python",
      "args": [
        "-m",
        "app.mcp_server"
      ],
      "cwd": "/Users/srinjoyroy/Documents/Paypal AI hackathon/backend",
      "env": {
        "GATEWAY_URL": "http://127.0.0.1:8000",
        "INTENT_AGENT_API_KEY": "dev_agent_key_placeholder",
        "PYTHONPATH": "."
      }
    }
  }
}
```

---

## 🔄 Example Session: Autonomous Self-Healing Flow

Here is a typical transcript showing how an untrusted agent operates through the Intent MCP server:

### Step 1: Discover Products
```json
// Agent Tool Call: search_products
{
  "query": "ThinkPad",
  "limit": 3
}

// MCP Server Response:
[
  {
    "product_id": "staples-thinkpad-p1-001",
    "title": "Lenovo ThinkPad P1 Gen 6",
    "merchant_domain": "staples.com",
    "price": 1899.99,
    "currency": "USD",
    "attributes": {
      "ram": "32GB",
      "storage": "1TB SSD",
      "cpu": "Intel Core i7-13700H"
    },
    "in_stock": true
  },
  {
    "product_id": "staples-thinkpad-e14-002",
    "title": "Lenovo ThinkPad E14 Gen 5",
    "merchant_domain": "staples.com",
    "price": 899.99,
    "currency": "USD",
    "attributes": {
      "ram": "8GB",
      "storage": "512GB SSD",
      "cpu": "Intel Core i5-1335U"
    },
    "in_stock": true
  }
]
```

### Step 2: Agent Attempts Non-Compliant Purchase (Spec Mismatch)
The agent erroneously selects `staples-thinkpad-e14-002` (which only has 8GB RAM, while the owner's mandate requires `min_ram: "16GB"`).

```json
// Agent Tool Call: submit_order_intent
{
  "mandate_id": "mandate_corp_eng_001",
  "product_id": "staples-thinkpad-e14-002",
  "merchant_domain": "staples.com",
  "quantity": 1
}

// Firewall Blocks with Remediation JSON:
{
  "status": "BLOCKED",
  "decision": "BLOCKED",
  "blocking_rules": ["ATTRIBUTE_MISMATCH"],
  "remediation": {
    "action": "CORRECT_ATTRIBUTES",
    "unmet_attributes": {
      "ram": {
        "expected": "16GB",
        "actual": "8GB"
      }
    },
    "suggested_action": "Select a product variant with at least 16GB RAM as mandated by mandate_corp_eng_001."
  }
}
```

### Step 3: Agent Self-Heals and Retries with Compliant Product
The agent parses the remediation feedback, sees that `staples-thinkpad-p1-001` satisfies the 16GB requirement (it has 32GB), and re-submits:

```json
// Agent Tool Call: submit_order_intent
{
  "mandate_id": "mandate_corp_eng_001",
  "product_id": "staples-thinkpad-p1-001",
  "merchant_domain": "staples.com",
  "quantity": 1
}

// Firewall Verifies & Executes:
{
  "status": "VERIFIED_READY_FOR_PAYPAL",
  "decision": "ALLOWED",
  "blocking_rules": [],
  "paypal_order_id": "ORDER_SANDBOX_7894231",
  "captured_amount": "1899.99",
  "remediation": null,
  "audit_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

---

## Intent MCP Architecture in Action

<!-- Placeholder for MCP Architecture Diagram / Screenshot: Curated assets will be placed in docs/images/ -->


