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

## Cryptographically Signed Mandates (Ed25519)

Mutable, unauthenticated policies are replaced with **cryptographically signed mandates** (`backend/app/mandate.py`):
1. **Mandate Contents:** Binds `mandate_id` (UUID), `owner_id`, `agent_id`, `max_order_total`, `auto_approve_under`, `max_quantity`, `required_attributes` (e.g. RAM/storage), `allowed_domains`, `required_availability`, cumulative limits (`daily_limit`, `weekly_limit`, `per_merchant_limit`, `max_orders_per_hour`), `issued_at`, `expires_at`, and `nonce`.
2. **Deterministic Canonical Hashing:** A SHA-256 `policy_hash` is calculated over the canonical JSON of all constraint fields.
3. **Ed25519 Signature:** Signed with the server's private key (`MANDATE_SIGNING_KEY` in env; ephemeral dev key auto-generated on first run with security warning). Public key exposed at `GET /api/mandate/public-key`.
4. **Agent & Admin RBAC Authentication:**
   - **Agent Endpoints:** Require `X-Agent-Key` (hashed in SQLite DB, verified via constant-time comparison). Rejects with `MANDATE_AGENT_MISMATCH` if an agent attempts to spend under another agent's mandate.
   - **Admin Endpoints:** Protected by `ADMIN_API_KEY` (sent in `X-Admin-Key` or `Authorization: Bearer`). Required for `POST /api/mandates`, `POST /api/mandates/{id}/revoke`, `PUT /api/policy`, `POST /api/paypal/capture/{order_id}`, and refunds.
5. **Deterministic Rejection Codes:**
   - `MANDATE_NOT_FOUND`
   - `MANDATE_EXPIRED`
   - `MANDATE_REVOKED`
   - `MANDATE_SIGNATURE_INVALID`
   - `MANDATE_AGENT_MISMATCH`

---

## Atomic Budget Reservations, Velocity Limits & Idempotency

To eliminate concurrency exploits (where multiple parallel agent requests overspend before balances commit), double charges on retries, and budget exhaustion across merchants, Intent implements an **Atomic Budget Reservation and Idempotency Engine** (`backend/app/reservation.py`):

```
                                    POST /api/verify-and-pay
                                 (Idempotency-Key, X-Agent-Key)
                                               │
                                               ▼
                              ┌──────────────────────────────────┐
                              │ Strict Idempotency Check         │
                              │  - Key match + FP match ──> Cache│
                              │  - Key match + FP drift ──> 409  │
                              └────────────────┬─────────────────┘
                                               │ (New Key)
                                               ▼
                              ┌──────────────────────────────────┐
                              │ Rules 1–3 Engine Verification    │
                              │ (Domain, Stock, Attributes, Qty) │
                              └────────────────┬─────────────────┘
                                               │ (Passed)
                                               ▼
                              ┌──────────────────────────────────┐
                              │ Atomic Budget Reservation        │
                              │ SQLite BEGIN IMMEDIATE Lock      │
                              │  - Sweep stale (>15 min)         │
                              │  - Velocity (orders/hour)        │
                              │  - Cumulative Daily Window       │
                              │  - Cumulative Weekly Window      │
                              │  - Per-Merchant Window           │
                              └────────────────┬─────────────────┘
                                               │ (Reserved)
                                               ▼
                              ┌──────────────────────────────────┐
                              │ Execution-time Catalog Check     │
                              │ Re-verify Channel3 ground truth  │
                              │ Price drift > 1% ──> PRICE_DRIFT │
                              └────────────────┬─────────────────┘
                                               │ (Passed)
                                               ▼
                              ┌──────────────────────────────────┐
                              │ PayPal Settlement Execution      │
                              │ (PayPal-Request-Id propagation)  │
                              │ Success ──> COMMIT Reservation   │
                              │ Error   ──> RELEASE Reservation  │
                              │ Refund  ──> RESTORE Headroom     │
                              └──────────────────────────────────┘
```

1. **Strict Client Idempotency:**
   - Every `/api/verify-and-pay` call supports the `Idempotency-Key` header.
   - The gateway computes a SHA-256 fingerprint of `(mandate_id, product_id, merchant_domain, quantity)`.
   - Replaying the same key with identical payload returns the cached response with zero duplicate charges.
   - Replaying the same key with altered parameters returns `409 IDEMPOTENCY_KEY_REUSED`.
   - Derives a deterministic 36-character `PayPal-Request-Id` to guarantee deduplication on PayPal's payment processing network.
2. **Atomic Budget Reservation (`BEGIN IMMEDIATE`):**
   - Serializes concurrent transactions at the database engine level, preventing race condition overspending.
   - Computes spend currently `RESERVED` or `COMMITTED` within the mandate's daily, weekly, and per-merchant windows.
   - Checks velocity against `max_orders_per_hour`.
   - Rejects with `DAILY_LIMIT_EXCEEDED`, `WEEKLY_LIMIT_EXCEEDED`, `MERCHANT_LIMIT_EXCEEDED`, or `VELOCITY_LIMIT_EXCEEDED`.
   - Provides exact `remaining_headroom` in the machine-readable remediation payload.
3. **Execution-time Price Drift Verification:**
   - Re-fetches catalog pricing and availability right before PayPal execution.
   - If unit price drifted by more than `PRICE_DRIFT_TOLERANCE` (default 1%), releases the reservation and blocks with `PRICE_DRIFT`.
4. **Reservation Lifecycle & Auto-Sweep:**
   - Commits on PayPal capture success.
   - Releases on PayPal failure or timeout.
   - Admin refunds (`POST /api/paypal/refund/{capture_id}`) automatically release the reservation and restore headroom.
   - Background worker sweeps and releases reservations stuck in `RESERVED` for over 15 minutes.

---

## Tamper-Evident Hash-Chained Audit Log

Intent features an enterprise-grade cryptographic audit trail (`backend/app/audit.py`) providing mathematical non-repudiation and tamper-evidence across all firewall decisions:

```
GENESIS BLOCK ("0"*64)
       │
       ▼
┌──────────────┐     SHA-256(prev_hash || canonical_json)     ┌──────────────┐
│ Event seq #1 │ ───────────────────────────────────────────> │ Event seq #2 │ ───> ...
└──────────────┘                                              └──────────────┘
```

1. **Cryptographic Chaining:**
   - Every state transition (mandate creation/revocation, purchase request, 4-rule evaluations, blocks, atomic reservations, price drift halts, PayPal orders, captures, and refunds) records an immutable event in `audit_events`.
   - Each event incorporates the SHA-256 hash of its immediate predecessor: `event_hash = SHA-256(prev_hash || canonical_json(event_fields))`.
   - Block #1 anchors to a fixed 64-character genesis hash (`0` * 64).
2. **Fork Prevention & Serialization:**
   - Appends are serialized using in-memory locks and SQLite `BEGIN IMMEDIATE` transactions, ensuring 50+ concurrent requests cannot fork the chain or produce orphaned blocks.
3. **Continuous Integrity Verification (`GET /api/audit/verify`):**
   - Walks the chain from block 1 to head, confirming unbroken sequence numbering (`seq == expected`), valid predecessor linkage (`prev_hash == prior.event_hash`), and payload integrity (`hmac.compare_digest`).
   - If any past record, timestamp, or payload is modified or deleted directly in SQLite, the endpoint immediately detects it and returns `{valid: false, first_broken_seq: N}`.
4. **Signed Offline Export (`GET /api/audit/export`):**
   - Exports the entire audit chain as JSON, with the final chain head signed by the system's Ed25519 private key.
   - Auditors can verify the log completely offline with zero server dependencies using:
     ```bash
     python scripts/verify_audit_export.py path_to_export.json
     ```
5. **Video & Live Demo Tamper Injection (`scripts/tamper_demo.py`):**
   - A dedicated developer utility to simulate database tampering live:
     ```bash
     # Inspect chain status
     python scripts/tamper_demo.py status

     # Inject unauthorized edit into block #2
     python scripts/tamper_demo.py tamper --seq 2

     # Restore original authentic block
     python scripts/tamper_demo.py restore
     ```
   - In the AG Grid dashboard, clicking **"Verify chain"** instantly turns the badge red: `CHAIN: TAMPERED (Block #2)`.

---

## Model Context Protocol (MCP) Server & Human Approval Channel

Intent extends native compatibility to autonomous AI agents through the **official Model Context Protocol (MCP)** Python SDK and an enterprise human-in-the-loop approval escalation channel:

```
┌─────────────────────────────────┐
│     AI Agent (Claude / Cursor)  │
└────────────────┬────────────────┘
                 │ MCP Protocol (JSON-RPC stdio)
                 ▼
┌─────────────────────────────────┐
│   Intent MCP Server (Port 8000) │
│   - Holds Agent API Key only    │
│   - Zero Admin Operations       │
└────────────────┬────────────────┘
                 │ HTTP (Ed25519 Mandate)
                 ▼
┌───────────────────────────────────────────────────────────────┐
│                    Intent Gateway Firewall                    │
│                                                               │
│   - Reference IDs only (agent cannot set price/specs/policy)  │
│   - Atomic Budget Reservation & Cumulative Limits             │
│   - Tamper-Evident Hash-Chained Audit Log                     │
│                                                               │
│        Order <= $1,000                   Order > $1,000 / New │
│               │                                   │           │
│               ▼                                   ▼           │
│   ┌───────────────────────┐           ┌───────────────────┐   │
│   │  Autonomous Capture   │           │ Human Escalation  │   │
│   │  PayPal Orders v2     │           │ Console/TG/Email  │   │
│   └───────────────────────┘           └─────────┬─────────┘   │
└─────────────────────────────────────────────────┼─────────────┘
                                                  │
                                                  ▼
                                       ┌─────────────────────┐
                                       │ Single-Use Token    │
                                       │ 15-min Expiry       │
                                       │ Re-run Rules & Drift│
                                       └─────────────────────┘
```

### 1. Intent MCP Server (`backend/app/mcp_server.py`)
- Implemented using the official Python MCP SDK (`mcp>=1.0.0`). Run standalone via:
  ```bash
  python -m app.mcp_server
  ```
- **Reference IDs Only:** Untrusted agents are only permitted to submit `mandate_id`, `product_id`, `merchant_domain`, and `quantity`. Agents cannot tamper with prices, titles, specs, policy values, or PayPal fields.
- **Tools Exposed:**
  - `search_products(query, limit=5)`: Read-only catalog search via Channel3.
  - `submit_order_intent(mandate_id, product_id, merchant_domain, quantity=1)`: Submits purchase intent to the firewall engine.
  - `get_mandate_status(mandate_id)`: Checks active constraints and headroom.
  - `get_order_status(attempt_id)`: Checks order state and capture ID.
- **Zero Admin Capabilities:** The MCP server strictly forbids tools for creating/modifying mandates, approving orders, or issuing refunds.
- **Structured Remediation for Self-Correction:** When blocked, tools return structured remediation JSON allowing the agent to self-heal.
- Detailed setup instructions for Claude Desktop and other MCP clients are available in [docs/MCP.md](docs/MCP.md).

### 2. Human Approval Channel & Escalation Policies (`backend/app/approvals.py`)
- Orders exceeding the mandate's `auto_approve_under` threshold ($1,000.00 default) or orders targeting a **first-time merchant domain** automatically trigger supervisor escalation.
- **Pluggable Notifier Interface (`backend/app/notifier.py`):**
  - **Console Notifier:** Default for local demos and testing.
  - **Telegram Bot Notifier:** Real-time push alerts via `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  - **SMTP Email Notifier:** Rich HTML email notifications with 1-click decision links via SMTP.
- **Cryptographic Single-Use Tokens:**
  - Generated via `secrets.token_urlsafe(32)`.
  - Stored strictly as SHA-256 hashes in SQLite. Plaintext tokens are never stored.
  - Strict 15-minute expiration window. Expired tokens release budget reservations and return HTTP 410.
  - Replay rejection: Replaying an already resolved token is rejected with HTTP 409.
- **Execution-Time Re-Verification:**
  - Upon human approval, the gateway re-fetches catalog specs and checks for price drift before PayPal capture. If the price drifted, the order blocks and releases reserved headroom.

### 3. Emergency Admin Kill Switch (`POST /api/agents/{id}/pause`)
- Administrators can immediately pause compromised or misbehaving agents.
- When paused, all in-flight and future requests from that agent are immediately rejected with HTTP 403 `AGENT_PAUSED`.
- Paused/resumed state changes are logged to the tamper-evident audit ledger and toggleable directly from the operator dashboard header.

---

## Automated Pytest Suite

Intent includes 44 automated unit, integration, and security adversarial tests covering all 4 rules, rate limiter circuit breakers, signed mandate cryptography, RBAC, atomic concurrency, idempotency, price drift, hash-chained audit tamper-evidence, MCP protocol isolation, and human approval channel security:

```bash
PYTHONPATH=backend backend/venv/bin/pytest backend/tests/ -v
```

```
backend/tests/test_audit_chain.py::test_valid_audit_chain_verifies PASSED
backend/tests/test_audit_chain.py::test_tampered_field_detected PASSED
backend/tests/test_audit_chain.py::test_deleted_event_detected PASSED
backend/tests/test_audit_chain.py::test_reordered_events_detected PASSED
backend/tests/test_audit_chain.py::test_50_concurrent_appends_keep_chain_valid PASSED
backend/tests/test_audit_chain.py::test_offline_export_verification PASSED
backend/tests/test_benchmark.py::test_benchmark_loader_validates_yaml_schema PASSED
backend/tests/test_benchmark.py::test_offline_mode_is_deterministic PASSED
backend/tests/test_benchmark.py::test_metrics_math_correct_on_fixture PASSED
backend/tests/test_benchmark.py::test_endpoint_get_benchmark_latest PASSED
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
backend/tests/test_mandate.py::test_tampering_field_after_signing_rejected PASSED
backend/tests/test_mandate.py::test_expired_mandate_rejected PASSED
backend/tests/test_mandate.py::test_revoked_mandate_rejected PASSED
backend/tests/test_mandate.py::test_agent_key_cannot_use_another_agent_mandate PASSED
backend/tests/test_mandate.py::test_agent_key_cannot_create_revoke_modify_mandate PASSED
backend/tests/test_mandate.py::test_mandate_signed_with_different_key_rejected PASSED
backend/tests/test_mandate.py::test_old_unauthenticated_policy_update_fails PASSED
backend/tests/test_mandate.py::test_public_key_endpoint PASSED
backend/tests/test_mcp_and_approvals.py::test_token_reuse_is_rejected PASSED
backend/tests/test_mcp_and_approvals.py::test_expired_token_is_rejected PASSED
backend/tests/test_mcp_and_approvals.py::test_approval_reruns_rules_and_blocks_if_price_drifted PASSED
backend/tests/test_mcp_and_approvals.py::test_paused_agent_is_blocked PASSED
backend/tests/test_mcp_and_approvals.py::test_mcp_tools_cannot_reach_admin_operations PASSED
backend/tests/test_mcp_and_approvals.py::test_mcp_block_response_contains_remediation_json PASSED
backend/tests/test_reservation_and_idempotency.py::test_concurrent_requests_daily_limit PASSED
backend/tests/test_reservation_and_idempotency.py::test_sequential_orders_exceeding_daily_limit PASSED
backend/tests/test_reservation_and_idempotency.py::test_idempotency_key_replay_returns_cached_response PASSED
backend/tests/test_reservation_and_idempotency.py::test_idempotency_key_changed_quantity_returns_409 PASSED
backend/tests/test_reservation_and_idempotency.py::test_paypal_failure_releases_reservation_and_refund_restores_headroom PASSED
backend/tests/test_reservation_and_idempotency.py::test_price_drift_above_tolerance_blocks_order PASSED

======================== 44 passed in 3.60s =========================
```

---

## Adversarial Benchmark: Unprotected Agent vs. Intent Firewall

To empirically prove that an unprotected agent gets tricked and the same agent behind Intent does not, Intent includes a reproducible adversarial benchmark suite (`benchmark/`).

### Benchmark Architecture & Runners

1. **Attack Catalog (`benchmark/attacks.yaml`):**
   Contains **72 test cases** across **11 exploit categories** plus 16 benign controls:
   - `spec_spoofing`: Text claims 16GB RAM on 8GB hardware or unverifiable models.
   - `quantity_tampering`: Injections inducing multi-unit orders exceeding user limits.
   - `domain_swap`: Routing purchases to unapproved external storefronts.
   - `lookalike_domains`: Phishing & typo-squatted domains (`st4ples.com`, `best-buy.com`).
   - `hidden_text_injection`: Zero-width formatting, HTML comments, and CSS `display:none` payloads.
   - `markdown_injection`: Misleading hyperlinks and injected Markdown tables.
   - `instruction_override`: Direct system prompts attempting to wipe spending constraints.
   - `multilingual_injection`: Exploits in Spanish, French, German, Chinese, and Japanese.
   - `fake_system_messages`: Spoofed PayPal security alerts and admin authorizations.
   - `mandatory_minimum_quantity`: Fabricated vendor MOQ rules forcing 2+ units.
   - `price_claims`: Deceptive discount claims hiding charges exceeding budget caps.
   - `benign_control`: 16 legitimate purchases that must be preserved and allowed.

2. **Dual-Path Runner Architecture:**
   - **Baseline (No Firewall):** The untrusted shopping agent processes the merchant listing and its output is accepted as-is by a mock payment function without firewall verification.
   - **Protected (Intent Firewall):** The exact same agent output is intercepted by the 4-rule deterministic engine. Specs and prices are checked server-to-server against Channel3 ground truth.

3. **Execution Modes:**
   - `offline`: Deterministic, CI-safe mode using recorded agent responses from `benchmark/recorded/`.
   - `gemini`: Live execution with Google Gemini (`gemini-1.5-flash`).
   - `openai`: Live execution with OpenAI (`gpt-4o-mini`).

### Reproducing Benchmark Results

Run the automated benchmark via Makefile:
```bash
# Run deterministic CI benchmark (3 runs per case, 72 cases):
make benchmark

# Run live benchmark with Gemini:
make benchmark-gemini

# Run live benchmark with OpenAI:
make benchmark-openai
```

### Empirical Results Summary

| Metric | Unprotected Agent (Baseline) | Behind Intent Firewall | Security Impact |
| :--- | :---: | :---: | :---: |
| **Attack Success Rate (ASR)** | **100.0%** | **0.0%** | 🟢 **-100.0% Exploit Elimination** |
| **False Positive Rate (FPR)** | 0.0% | 0.0% | 🟢 Zero legitimate purchases blocked |
| **Total Attacks Neutralized** | 0 / 168 | **168 / 168** | 🛡️ **100% Defense Against Injections** |
| **Median Firewall Latency** | N/A | **0.018 ms** | ⚡ Sub-millisecond pure-code execution |

### Generated Reports & Endpoints
- **JSON Manifest:** `benchmark/results/latest.json`
- **Markdown Summary:** `benchmark/results/summary.md`
- **Standalone HTML Report:** `benchmark/results/report.html`
- **REST API:** `GET /api/benchmark/latest`
- **Frontend Dashboard:** Interactive **Benchmark** tab featuring AG Charts horizontal bar chart comparing baseline vs protected ASR per category, latency breakdown, and interactive test case audit drawer.

---

## Minimalist Enterprise Design System & Visual Walkthrough

Intent features a calm, dense, precise enterprise fintech security console built with flat white panels, thin 1px borders, generous whitespace, strong typographic hierarchy, and restrained PayPal-inspired color.

### Design Tokens (`frontend/src/styles/tokens.css`)
- **Brand Palette:** Brand Navy `#003087` (wordmark, primary headings, table headers), Action Blue `#0070E0` (primary buttons, active tabs, links, focus), Action Hover `#005EC4`, Text Primary `#0F1B33`, Text Secondary `#55627A`, Text Disabled `#8C97AA`.
- **Surfaces & Borders:** Panels `#FFFFFF`, Subtle Page Gradient `linear-gradient(180deg, #FFFFFF 0%, #F3F6FA 100%)`, 1px Border `#E3E8EF`, Strong Border `#CBD3DF`, Hover Row `#F6F8FA`.
- **Status Tokens (Paired Icon + Text):** Success `#0A7D4F` on `#E8F5EE`, Danger `#B42318` on `#FDECEA`, Warning `#9A5B00` on `#FFF4E0`, Info `#0058B8` on `#E8F1FD`.
- **Typography & Radii:** Inter for UI, JetBrains Mono for data, IDs, hashes, and currency with `tabular-nums`. Radii: 6px for cards, panels, inputs, and buttons; 4px for rectangular tags. Strictly 0 pill shapes (no 999px or 50% on rectangular elements, maximum 8px radius).
- **Anti-Slop Guarantees:** 0 emojis (Lucide 16px icons only), 0 gradients on controls/cards, 0 neumorphic shadows/glow/blur, 0 nested cards.
- **Accessibility:** Strict WCAG AA compliance (text contrast >= 4.5:1 across all tabs), visible focus rings (`2px solid #0070E0`), `prefers-reduced-motion` support, and zero horizontal body overflow across mobile (375px), tablet (768px), laptop (1024px/1280px), and desktop (1440px).

<!-- DEMO MEDIA PLACEHOLDER: Add demo video link and curated high-resolution UI walkthrough images to docs/images/ -->

---

## Verification & Test Suite

Intent is built with rigorous automated verification covering cryptographic integrity, route authorization, prompt injection defense, multi-tenant isolation, and bundle security:

```bash
# 1. Run complete 81-test automated pytest verification suite
make test

# 2. Run deterministic offline adversarial benchmark (56 attacks + 16 benign controls = 72 cases, 216 runs)
make benchmark

# 3. Audit frontend production bundle and source code for secret leaks
make scan-secrets

# 4. Verify multi-tenant demo sandbox isolation end-to-end (two concurrent sessions)
make verify-e2e

# 5. Export and cryptographically verify the append-only SHA-256 audit chain offline
make verify-export

# 6. Demonstrate active tamper detection by altering an audit event in the database
make tamper-demo
```

### Verification Results Summary

| Verification Gate | Command | Test Cases / Runs | Status | Primary Invariant Proven |
| :--- | :--- | :---: | :---: | :--- |
| **Complete Pytest Suite** | `make test` | 81 tests | 🟢 **81 Passed (100%)** | Zero regression across mandates, reservations, webhooks, anchors, MCP, and rate limiters. |
| **Adversarial Benchmark** | `make benchmark` | 72 cases (216 runs) | 🟢 **0.0% Protected ASR** | 100% of prompt injections, spec spoofing, and quantity tampering blocked before PayPal. 0% FPR. |
| **Bundle Secrets Scanner** | `make scan-secrets` | Full `dist/` & `src/` | 🟢 **Zero Leaks Found** | No administrative API keys, PayPal secrets, or `localStorage` credential storage in client bundle. |
| **Route Auth Regression** | `test_mandate.py` | Full route table | 🟢 **100% Protected** | All mutating endpoints require `require_admin_key` or cryptographic session verification. |
| **Multi-Tenant E2E Isolation** | `make verify-e2e` | 2 concurrent sessions | 🟢 **Zero Cross-Tenant Leak** | Session A cannot pause, resume, read, resolve, or refund Session B's resources (HTTP 403). |
| **Merkle Audit Verification** | `make verify-export` | Full event chain | 🟢 **Cryptographically Valid** | Ed25519-signed manifest verifies continuous SHA-256 link from genesis to current event. |

---

## Security, Threat Model & Multi-Tenant Sandbox

For in-depth architectural and cryptographic documentation, see:
- 🏗️ **[System Architecture & Persistence](docs/ARCHITECTURE.md):** Complete specifications for the 4-rule deterministic engine, Ed25519 mandates, persistent disk layout, and PayPal webhook cryptographic anchoring.
- 📖 **[Endpoint Authentication & Mutation Matrix](docs/ENDPOINT_AUTH_MATRIX.md):** Complete catalog of all endpoints, authentication requirements, and state mutation properties.
- 🛡️ **[Threat Model & Security Architecture](docs/THREAT_MODEL.md):** Formal adversary classes, trust boundaries, what Intent defends, and honest out-of-scope boundaries.
- 🔌 **[MCP Server Specification](docs/MCP.md):** Integration guide for Model Context Protocol agent tool calls.
- 🎨 **[Design System Contract](docs/DESIGN.md):** Enterprise fintech design tokens, typography, and anti-slop rules.

### Multi-Tenant Demo Sandbox Architecture
In public demo mode (`APP_MODE=demo`), external visitors and hackathon evaluators can interact with the firewall without administrative keys:
1. **Cryptographically Signed Session Cookies:** Visitors receive an `intent_session` HttpOnly cookie signed via HMAC-SHA256 (`SESSION_SECRET`).
2. **Dedicated Sandbox Identifiers:** Each visitor is assigned a unique `agent_id` and dedicated Ed25519-signed `mandate_id`.
3. **Strict Resource Isolation:** All `/api/demo/*` routes filter by `session_id`. Attempting to resolve another session's approval or refund another session's capture is blocked with `HTTP 403 Forbidden`.
4. **Per-Session Rate Limiting & TTL:** Max 30 requests/hour per session with a 2-hour TTL and automated cleanup sweep.

---

## Honest Boundaries & Known Limitations

1. **Pre-Purchase Digital Boundary (What We Do Not Defend):**
   - **Warehouse & Counterfeit Fulfillment:** Intent verifies merchant domain authorization and catalog structured attributes. It cannot physically inspect physical warehouse merchandise.
   - **Unspecified Buyer Desires:** If a buyer signs a mandate specifying `ram: 16GB` without specifying brand or color, the gateway permits any 16GB laptop on an approved domain.
   - **Post-Purchase RMAs / Defects:** Defective items delivered post-purchase belong to standard post-delivery dispute channels.
   - **Root Key Compromise:** If an adversary compromises `MANDATE_SIGNING_KEY` on the host, the root of trust is broken. Production deployments require HSM or KMS key storage.
2. **Database Concurrency in Multi-Worker Deployments:**
   - The default development database uses SQLite with WAL mode (`aiosqlite`).
   - SQLite supports high-concurrency read operations, but write operations are serialized. For horizontal production clusters running multiple container replicas, PostgreSQL is recommended.
3. **PayPal Sandbox Latency:**
   - Live calls to PayPal Sandbox Orders v2 (`/v2/checkout/orders`) take between 1.2s and 4.5s depending on upstream sandbox load.
4. **Channel3 External Quotas:**
   - External catalog lookups utilize a 1-hour TTL cache and daily query limits. When external quotas are exhausted, Intent falls back seamlessly to pre-cached product fixtures.

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
