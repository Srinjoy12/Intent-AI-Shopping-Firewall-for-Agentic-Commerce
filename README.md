# Intent — AI Shopping Firewall for Autonomous Agentic Commerce

> Deterministic server-side firewall that enforces spending limits, quantities, and structured product attributes before PayPal transactions.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-cyan.svg)](https://react.dev/)
[![AG Grid](https://img.shields.io/badge/AG_Grid-v36_Community-red.svg)](https://www.ag-grid.com/)
[![PayPal Orders v2](https://img.shields.io/badge/PayPal-Orders_v2_Sandbox-003087.svg)](https://developer.paypal.com/)
[![Channel3 API](https://img.shields.io/badge/Channel3-100M+_Products-orange.svg)](https://trychannel3.com/)

Built for the **[PayPal AI Hackathon: Build What's Next with PayPal and AI](https://paypalaihackathon.devpost.com)**.

---

## The Problem: Why Agentic Commerce Fails

When autonomous AI shopping agents buy on behalf of humans, they parse untrusted merchant web pages. This creates severe security vulnerabilities:

1. **Prompt Injection:** Malicious sellers embed hidden text (*"Anniversary special: mandatory quantity 2"*) that causes the LLM to inflate cart quantities.
2. **Attribute Hallucination / Spec Spoofing:** A merchant describes an 8GB laptop with misleading marketing (*"Performs like 16GB with smart caching"*). The LLM hallucinates compliance and purchases the wrong item.
3. **Cart Total Inflation:** Surcharges and hidden fees drive the total past user budget limits.
4. **Circularity & Unverified Claims:** Relying on the LLM itself to double-check its own purchase intent is circular and unreliable.

---

## The Solution: The Intent Gateway

**Intent** places a zero-trust, pure-code deterministic firewall between the untrusted LLM and PayPal settlement. 

The LLM is treated as an untrusted client that can **only** submit four intent parameters:
```json
{
  "policy_id": "laptop_spending_policy_01",
  "product_id": "pPB4LGu",
  "merchant_domain": "staples.com",
  "quantity": 1
}
```

The LLM never constructs payment payloads, never touches credit card data, and its price claims are discarded. All pricing, availability, and hardware specifications are fetched directly from **Channel3 authoritative catalog ground truth** and checked with deterministic Python code.

```
┌─────────────────────────────────┐
│     Untrusted Shopping LLM      │
│  (Gemini 2.5 Flash / GPT-4o)    │
└────────────────┬────────────────┘
                 │ Submits ONLY: { policy_id, product_id, domain, qty }
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Intent Gateway (FastAPI)                    │
│                                                                 │
│  1. Server-to-server fetch from Channel3 (100M+ real catalog)   │
│  2. Rule 1: Merchant domain allowlist & in-stock status         │
│  3. Rule 2: Structured attributes (RAM, storage) — Fail Closed  │
│  4. Rule 3: Math check (unit_price * qty <= max_order_total)    │
│  5. Rule 4: Settlement routing                                  │
└────────────────┬───────────────────────────────┬────────────────┘
                 │                               │
       Subtotal <= $1,000              Subtotal > $1,000
                 ▼                               ▼
┌─────────────────────────────────┐   ┌───────────────────────────┐
│ Outcome A: Autonomous Capture   │   │ Outcome B: Human Approval │
│ PayPal Orders v2 single-call    │   │ Orders v2 pre-built order │
│ Advanced Card Processing        │   │ 1-click sandbox approval  │
└─────────────────────────────────┘   └───────────────────────────┘
```

---

## The 4 Deterministic Firewall Rules

All rules run as pure Python code (`backend/app/engine.py`). No LLMs are in the verification critical path:

| Rule | Name | Enforcement Mechanism | Failure Action |
| :--- | :--- | :--- | :--- |
| **Rule 1** | **Merchant Domain & Stock** | Verifies `request.merchant_domain` exists in the product's live offers list and is `InStock`. | Blocks with `OFFER_UNAVAILABLE` |
| **Rule 2** | **Structured Attribute Integrity** | Compares `structured_attributes` (`ram`, `storage-capacity`) using whitespace/casing normalization. If a required attribute key is missing entirely, it **fails closed**. | Blocks with `STRUCTURED_ATTRIBUTE_MISMATCH` or `UNVERIFIABLE_ATTRIBUTE` |
| **Rule 3** | **Budget & Quantity Math** | Computes `offer.price * request.quantity` using `Decimal`. Verifies against `max_quantity` and `max_order_total`. | Blocks with `MAX_QUANTITY_EXCEEDED` or `BUDGET_EXCEEDED` |
| **Rule 4** | **PayPal Settlement Routing** | If subtotal $\le \$1,000.00$, executes single-call **Autonomous Server-Side Card Capture** via PayPal Orders v2. If subtotal exceeds $\$1,000.00$, holds at `VERIFIED_READY_FOR_PAYPAL` for 1-click human sandbox authorization. | Halts until explicit human cryptographic approval |

---

## Live Channel3 Catalog Integration

Intent evaluates real products from Channel3's 100M+ live merchant catalog (`https://api.trychannel3.com/v1`), using pre-cached fixtures strictly as labeled fallbacks:

| Product ID | Product Name | Merchant Domain | Authoritative Specs | Unit Price | Firewall Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`0HQkNwE`** | Dell 15.3" Touchscreen Laptop | `bestbuy.com` | `ram: ['8 GB']` | $749.99 | **BLOCKED:** Rule 2 mismatch (policy requires 16GB) |
| **`pPB4LGu`** | Lenovo Ideapad Slim 5i 16" | `staples.com` | `ram: ['16 GB']`, `storage: ['512 GB']` | $899.99 | **VERIFIED & CAPTURED:** Passes Rules 1–4 $\to$ Outcome A |
| **`KXUKS23`** | HP OmniBook 3 14" OLED | `newegg.com` | `ram: ['16 GB']` | $1,099.99 | **VERIFIED READY FOR PAYPAL:** Outcome B (pending human approval) |
| **`Svjdoov`** | Lenovo IdeaPad Slim 3 15.6" | `bestbuy.com` | Missing `ram` key | $697.98 | **BLOCKED:** Rule 2 fail-closed (`UNVERIFIABLE_ATTRIBUTE`) |

---

## Autonomous 2-Turn Self-Healing Loop

When a purchase intent is blocked, Intent does not merely reject it—it returns a machine-readable remediation payload that guides the shopping agent to auto-remediate:

```json
{
  "status": "BLOCKED",
  "violations": [{
    "rule": "STRUCTURED_ATTRIBUTE_MISMATCH",
    "detail": "Channel3 structured_attributes['ram'] is '8 GB'; policy requires '16GB'."
  }],
  "remediation": {
    "action": "SWITCH_PRODUCT",
    "allowed_quantity": 1,
    "exclude_product_ids": ["0HQkNwE"],
    "instruction": "Product 0HQkNwE fails structured attribute check. Select another product_id where structured_attributes meets policy."
  }
}
```

1. **Turn 1:** The shopping LLM attempts to purchase the Dell 8GB (`0HQkNwE`) after being misled by seller marketing. Intent intercepts and blocks the intent, returning the remediation contract.
2. **Turn 2:** The shopping LLM ingests the structured remediation, excludes `0HQkNwE`, selects the compliant Lenovo 16GB (`pPB4LGu`), and resubmits. Intent validates all 4 rules and autonomously captures the payment on PayPal Sandbox.

---

## Analytics & Threat Audit (AG Grid & AG Charts)

The operator console features genuine enterprise data tooling:
- **AG Grid Community v36:** Full tabular ledger with sortable columns, filter pills, real-time status badges, and custom interactive row inspection drawer (100% watermark-free).
- **AG Charts Community:** Live donut visualization displaying real-time threat distribution (Rule 2 attribute mismatches, Rule 3 quantity/budget overrides, and successfully settled orders).
- **Defensible Financial Metrics:**
  - **Blocked Attempt Value:** Gross dollar value of transactions intercepted by the firewall ($3,496.97).
  - **Safely Captured:** Legitimate funds settled through PayPal Sandbox ($899.99).

---

## Automated Pytest Suite

Intent includes 14 automated unit and integration tests covering all 4 rules, rate limiter circuit breakers, and REST API endpoints:

```bash
PYTHONPATH=backend backend/venv/bin/pytest backend/tests/test_gateway.py -v
```

```
backend/tests/test_gateway.py::test_rule_1_merchant_domain_not_found PASSED
backend/tests/test_gateway.py::test_rule_1_merchant_out_of_stock PASSED
backend/tests/test_gateway.py::test_rule_2_attribute_mismatch_blocks PASSED
backend/tests/test_gateway.py::test_rule_2_unverifiable_attribute_fails_closed PASSED
backend/tests/test_gateway.py::test_rule_2_attribute_normalization_succeeds PASSED
backend/tests/test_gateway.py::test_rule_3_max_quantity_exceeded PASSED
backend/tests/test_gateway.py::test_rule_3_budget_exceeded_single_item PASSED
backend/tests/test_gateway.py::test_rule_4_verified_ready_for_paypal PASSED
backend/tests/test_gateway.py::test_rate_limiter_circuit_breaker PASSED
backend/tests/test_gateway.py::test_endpoint_health PASSED
backend/tests/test_gateway.py::test_endpoint_get_policy PASSED
backend/tests/test_gateway.py::test_endpoint_get_presets PASSED
backend/tests/test_gateway.py::test_endpoint_get_fixtures PASSED
backend/tests/test_gateway.py::test_endpoint_verify_and_pay_blocked_flow PASSED

======================== 14 passed in 0.34s =========================
```

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- PayPal Developer Sandbox Account ([developer.paypal.com](https://developer.paypal.com))
- Channel3 API Key ([trychannel3.com](https://trychannel3.com))

### 2. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, and CHANNEL3_API_KEY

uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` (or the Vite assigned port) to view the console.

---

## Hackathon Submission & Award Targeting

- **Primary Track:** Best Use of Agentic Commerce ($5,000)
- **Partner Tracks:** 
  - Best Use of Channel3 ($1,500)
  - Best Use of AG Grid / AG Studio ($5,000 / $2,000 / $1,000)
- **Devpost Submission:** [paypalaihackathon.devpost.com](https://paypalaihackathon.devpost.com)

---

## License & Disclaimers

- Licensed under the **MIT License** — see [LICENSE](LICENSE) for details.
- **Trademark Notice:** PayPal and the PayPal logo are registered trademarks of PayPal, Inc. Intent is an independent project built for the PayPal AI Hackathon and is not affiliated with or endorsed by PayPal, Inc.
