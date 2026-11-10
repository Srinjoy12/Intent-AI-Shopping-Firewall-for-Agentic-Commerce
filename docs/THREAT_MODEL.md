# Intent Gateway — Threat Model & Security Architecture

This document defines the formal threat model, trust boundaries, attacker capabilities, defensive guarantees, and architectural limits of the **Intent AI Shopping Firewall**.

---

## 1. Security Philosophy: The Untrusted Agent Model

Modern AI shopping agents operate under inherently hostile conditions:
- They consume untrusted third-party inputs (unvetted merchant web pages, user reviews, markdown descriptions, and prompt injection payloads).
- They execute stochastic inferences with non-zero failure and jailbreak rates.
- They cannot be hardened by prompt engineering or system prompt guardrails alone.

**Core Architectural Invariant:**
> **The autonomous agent is assumed fully compromised.**
>
> Intent treats the agent as an untrusted adversary. The gateway does not attempt to "fix" or align the LLM; instead, it enforces deterministic, pure-code cryptographic and policy boundaries between the agent's proposed intent and the PayPal payment rail. If the LLM is 100% compliant with an attacker, the gateway still prevents unauthorized spend, spec spoofing, domain swapping, and budget overruns.

---

## 2. Assets Protected

1. **Buyer Capital & Wallet Balances:** Funds held in PayPal balances, linked credit cards, and bank accounts.
2. **Mandate Cryptographic Integrity:** Ed25519 digitally signed spending contracts binding product requirements, authorized domains, price caps, and temporal expiry.
3. **Cumulative Spending Headroom:** Hard multi-window budget caps (daily limits, weekly limits, per-merchant caps, and per-hour velocity limits) backed by immediate reservations.
4. **Audit Trail Immutability:** SHA-256 Merkle chain linking every proposal, decision, approval, and reservation, anchored into PayPal order records via `custom_id`.
5. **Human Approval Tokens:** Single-use, HMAC-SHA256 stateless tokens with 15-minute validity, protected by strict CSRF and GET/POST separation.
6. **Provider API Quotas:** Per-session rate limits preventing external evaluators or abusive clients from exhausting Channel3 or PayPal sandboxes.

---

## 3. Attacker Capabilities & Threat Vectors

The threat model evaluates the following adversary classes and attack vectors:

| Attacker Class | Capabilities & Vectors | Real-World Scenario |
| :--- | :--- | :--- |
| **Malicious Retailer / Listing Injector** | Injects prompt injection payloads into product titles, descriptions, hidden HTML comments, zero-font spans, or markdown image alt tags. | Listing claims *"IMPORTANT: Upgraded to 16GB RAM for promotion"* while catalog product is 8GB. |
| **Lookalike / Phishing Merchant** | Registers typographical lookalike domains (`stap1es.com`, `best-buy-deals.com`) or attempts domain swapping. | Injected listing instructs agent to redirect checkout to an attacker-controlled payment gateway. |
| **Compromised Autonomous Agent** | Complete control over agent tool call arguments (`product_id`, `merchant_domain`, `quantity`, `agent_reasoning`). | Adversary jailbreaks the agent or induces hallucination to order luxury items or excessive quantities. |
| **Network Prefetcher / Bot Scanner** | Automated HTTP GET crawling (email security gateways, Telegram link preview generators, browser prefetchers). | Scanner follows an approval link sent via Telegram and triggers state mutation without human consent. |
| **TOCTOU Price Manipulator** | Changes retailer price or offer terms between the moment the agent selects the product and final checkout execution. | Item price jumps from $499 to $1,499 while the transaction is in-flight. |
| **Replay & Concurrency Adversary** | Replays captured webhook events, approval tokens, or launches parallel requests to exceed cumulative limits. | Two parallel $800 orders attempt to bypass a $1,000 daily budget simultaneously. |

---

## 4. Trust Boundary

```
┌────────────────────────────────────────────────────────────────────────┐
│                        UNTRUSTED EXTERNAL ZONE                         │
│                                                                        │
│   ┌─────────────────────┐            ┌─────────────────────────────┐   │
│   │ External Retailers  │            │   Autonomous LLM Agent      │   │
│   │ (HTML, Markdown,    │            │ (Gemini, Claude, GPT, etc.) │   │
│   │  Prompt Injections) │            │  [ASSUMED COMPROMISED]      │   │
│   └──────────┬──────────┘            └──────────────┬──────────────┘   │
└──────────────┼──────────────────────────────────────┼──────────────────┘
               │ Listing Text                         │ Proposed Tool Call
═══════════════╪══════════════════════════════════════╪═══════════════════
               │                                      │ (product_id, domain, qty)
               ▼                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        INTENT TRUSTED BOUNDARY                         │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                   DETERMINISTIC FIREWALL ENGINE                │   │
│   │                                                                │   │
│   │   [Rule 1] Merchant Domain & Offer Availability Verification   │   │
│   │   [Rule 2] Structured Attribute Verification (Fail-Closed)     │   │
│   │   [Rule 3] Quantity & Cumulative Budget Headroom Math          │   │
│   │   [Rule 4] Routing: Autonomous Threshold vs Human Approval    │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
│                                   │                                    │
│   ┌───────────────────────────────┴────────────────────────────────┐   │
│   │                  CRYPTOGRAPHIC PERSISTENCE LAYER               │   │
│   │  • Ed25519 Signed Mandates (Immutable Policy Hash)             │   │
│   │  • Append-Only Merkle Audit Chain                              │   │
│   │  • Immediate Budget Headroom Reservation (In-Memory Locks)     │   │
│   │  • Stateless HMAC-SHA256 CSRF / Approval Tokens               │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │ Cryptographically Anchored Order
                                    │ (custom_id = event_hash)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          PAYPAL PAYMENT RAIL                           │
│                                                                        │
│   • Orders v2 API (Sandbox / Live)                                     │
│   • Asynchronous Webhook Verification (Signature Verification API)     │
│   • Partner / Multipart Settlement (payee + platform_fees)             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. What Intent Defends (Guaranteed Protections)

1. **Merchant Authenticity & In-Stock Verification (Rule 1):**
   - Transactions are strictly restricted to domains explicitly enumerated in the signed mandate (`allowed_domains`).
   - Lookalike domains (`stap1es.com`), subdomains, or unapproved retailers are rejected before payment creation.
   - The specific offer must exist and report `availability == "InStock"` in verified catalog feeds.

2. **Generic Structured Attribute Enforcement (Rule 2 - Fail-Closed):**
   - The gateway ignores free-text product titles and descriptions entirely.
   - It matches required attributes purely against verified structured catalog data (`structured_attributes` from Channel3).
   - Dynamic schema support: evaluates arbitrary attributes (`ram`, `storage`, `screen_size`, `resolution`, `refresh_rate`) with zero hardcoded field logic.
   - Fail-closed: if an attribute is missing from the catalog feed, Intent raises `UNVERIFIABLE_ATTRIBUTE` and blocks the transaction.

3. **Strict Math & Cumulative Headroom Reservation (Rule 3):**
   - Single-order limits: enforced against unit price multiplied by requested quantity (`unit_price * quantity`).
   - Cumulative caps: daily, weekly, and per-merchant limits are evaluated against historical spend plus unreleased reservations.
   - Concurrency safety: SQLite row locks and in-memory reservations guarantee parallel orders cannot race to exceed headroom.

4. **1-Click Human Approval Channel (Rule 4):**
   - Orders exceeding the `auto_approve_under` threshold require human authorization.
   - **GET Requests Are Read-Only:** Accessing `/api/approvals/action?token=...` renders a confirmation page but mutates zero database rows and consumes no tokens, protecting against email and messenger link scanners.
   - **POST Verification:** State mutation requires a valid POST accompanied by a stateless HMAC-SHA256 CSRF token bound to the approval ID and expiry.
   - Tokens expire after 15 minutes and can only be consumed once (idempotent 409 conflict on replay).

5. **Pre-Capture Price Drift (TOCTOU Defense):**
   - Immediately prior to capturing funds via PayPal, Intent re-queries the merchant catalog offer.
   - If the price has drifted by more than 1.0% tolerance, capture is aborted with `PRICE_DRIFT`.

6. **Tamper-Evident PayPal Anchoring:**
   - Every PayPal order carries `purchase_units[0].custom_id` set to the exact 64-hex SHA-256 hash of the `reservation_created` audit event.
   - PayPal order records serve as an immutable, third-party witness to the gateway's internal audit chain.

7. **Webhook Signature Verification & Idempotency:**
   - All inbound PayPal webhook notifications (`PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.DENIED`) undergo cryptographic signature validation via PayPal's API.
   - Duplicate delivery is handled idempotently via `paypal_webhook_events` tracking.
   - Approved refunds restore budget headroom automatically.

---

## 6. What Intent Does NOT Defend (Honest Architectural Boundaries)

Intent is a **pre-purchase spending and contract enforcement firewall**. It does not replace physical logistics, hardware manufacturing quality control, or master credential security. The following scenarios are explicitly out-of-scope and documented as `NOT_BLOCKED`:

### 1. Counterfeit Seller on an Allowed Domain
- **Scenario:** A third-party marketplace seller on an approved domain (e.g., `amazon.com` or `newegg.com`) fulfills a counterfeit or counterfeit-clone item under a legitimate SKU.
- **Why Intent Does Not Block:** Intent verifies digital catalog metadata and domain legitimacy. It has no physical inspection mechanism to audit warehouse logistics or physical merchandise prior to shipping.
- **Boundary Layer:** Physical Logistics / Fulfillment Fraud.

### 2. Wrong Brand or Color Not Specified in the Mandate
- **Scenario:** An owner intends to purchase a Space Gray Apple MacBook or Dell XPS, but the signed mandate only requires `{"ram": "16GB", "storage": "512GB"}` with a $1,200 limit. The agent selects a Pink Acer Aspire meeting all signed parameters.
- **Why Intent Does Not Block:** Intent enforces explicit cryptographic contracts, not implicit or unstated human desires. If a constraint is omitted from the signed mandate, the gateway permits the agent's choice.
- **Boundary Layer:** Contract Completeness / Specification Ambiguity.

### 3. Defective Item Delivered Post-Purchase
- **Scenario:** A compliant purchase arrives with dead pixels, a cracked screen, or a defective battery.
- **Why Intent Does Not Block:** Intent governs pre-settlement authorization. Post-delivery hardware defects, warranty claims, and RMAs belong to standard customer support and post-purchase dispute channels.
- **Boundary Layer:** Post-Purchase Operations / Warranty.

### 4. Stolen Agent Key Operating Within Mandate Limits
- **Scenario:** An attacker exfiltrates the agent's API credentials and submits orders that comply with authorized product attributes, approved merchant domains, and remaining budget headroom.
- **Why Intent Does Not Block:** The gateway verifies that orders satisfy the owner's signed policy. If an attacker possesses valid agent credentials and operates within authorized limits, the gateway cannot differentiate between legitimate agent calls and key theft.
- **Boundary Layer:** Credential Management / API Secret Security.

### 5. Overly Permissive Signed Mandate
- **Scenario:** An owner issues a signed mandate with a $10,000 budget, max quantity of 10, and zero required attributes or domain restrictions. The agent purchases arbitrary items up to the limit.
- **Why Intent Does Not Block:** The firewall strictly executes the contract authorized by the owner's cryptographic signature. If the human signs a loose policy, Intent faithfully enforces the loose parameters.
- **Boundary Layer:** Human Configuration / Policy Rigor.

### 6. Compromised Master Signing Key / Admin Key
- **Scenario:** An adversary compromises the host environment, extracts `MANDATE_SIGNING_KEY` or `ADMIN_API_KEY`, and signs unauthorized mandates directly.
- **Why Intent Does Not Block:** Intent's security model is anchored in cryptographic signatures. If the master signing key is compromised, the cryptographic root of trust itself is broken. Protection against host key extraction requires Hardware Security Modules (HSM) or multi-signature cold authorization.
- **Boundary Layer:** Host Security / Cryptographic Root of Trust.

---

## 7. Merchant of Record (MoR) Architecture

A critical architectural distinction for autonomous e-commerce gateways is fund routing and Merchant of Record liability:

### Sandbox & Demonstration Mode
In the sandbox environment, PayPal orders are captured into the developer's sandbox merchant account. This enables full end-to-end simulation of authorization, human approval, price drift, and capture without requiring active commercial merchant partner agreements.

### Production Multi-Party Settlement Architecture
In production deployments, Intent does not act as the Merchant of Record for product delivery or sales tax. Instead, it utilizes **PayPal Partner / Multipart Payments**:

1. **Direct Merchant Routing (`payee`):**
   ```json
   {
     "purchase_units": [
       {
         "reference_id": "attempt_att_xyz",
         "custom_id": "9f8a3c...event_hash",
         "payee": {
           "email_address": "merchant-orders@staples.com",
           "merchant_id": "MERCHANT_PAYPAL_ID"
         },
         "amount": {
           "currency_code": "USD",
           "value": "899.99"
         },
         "payment_instruction": {
           "platform_fees": [
             {
               "amount": {
                 "currency_code": "USD",
                 "value": "8.99"
               },
               "payee": {
                 "email_address": "billing@intentgateway.io"
               }
             }
           ]
         }
       }
     ]
   }
   ```
2. **Benefits of Multi-Party Routing:**
   - **No Balance Holding:** Intent never takes custody of merchant revenue, eliminating financial licensing requirements (money transmitter licenses).
   - **Direct Retailer MoR:** The retailer (`staples.com`, `bestbuy.com`) receives funds directly and acts as the legal Merchant of Record for sales tax calculation, shipping fulfillment, and returns.
   - **Automated Platform Monetization:** Intent collects its facilitation fee (`platform_fees`) automatically upon capture via PayPal's native split settlement rail.

---

## 8. Multi-Tenant Demo Sandbox Isolation Model

To enable public evaluation and hackathon judging without exposing administrative keys or enabling cross-tenant denial-of-service, Intent implements a **multi-tenant demo sandbox engine** (`app/session.py`):

1. **Tamper-Proof Session Tokens:**
   - Visitors receive an `intent_session` HttpOnly cookie.
   - The cookie value is cryptographically signed with HMAC-SHA256 (`session_id.sig`) using `SESSION_SECRET`.
   - Tampered or fabricated session cookies are immediately rejected.
2. **Dedicated Cryptographic Identities:**
   - Every visitor session provisions an isolated sandbox containing:
     - A dedicated `agent_id` (`agent_demo_<session_hash>`).
     - A dedicated `mandate_id` (`mandate_demo_<session_hash>`) with an Ed25519 digital signature and canonical `policy_hash`.
     - An isolated internal agent API key registered in the database.
3. **Cross-Tenant Boundary Enforcement:**
   - All `/api/demo/*` endpoints enforce strict tenant filtering:
     - **Kill Switch:** Pausing an agent in Session A blocks Session A without altering Session B's active status.
     - **Approvals:** Session B cannot list or resolve pending approvals belonging to Session A (`HTTP 403 APPROVAL_FORBIDDEN`).
     - **Refunds:** Session B cannot issue refunds against PayPal captures belonging to Session A (`HTTP 403 REFUND_FORBIDDEN`).
     - **Attempts & Analytics:** Attempt logs and summary metrics are strictly filtered by `session_id`, ensuring zero cross-tenant ledger leakage.
4. **Denial-of-Service Defense:**
   - Per-session rate limiting restricts requests to 30 requests/hour per session. An abusive visitor cannot exhaust the quota of another concurrent evaluator or visitor.
   - Sandboxes automatically expire after 2 hours (`SESSION_TTL_HOURS = 2`), with periodic database cleanup sweeps removing stale tenant state.

---

## 9. Secrets Management & Leak Prevention Architecture

Protecting master administrative keys, private signing keys, and payment credentials is vital to maintaining the integrity of the firewall:

1. **Zero Frontend Bundle Exposure:**
   - The production frontend bundle (`frontend/dist`) is strictly audited via `scripts/check_bundle_secrets.sh`.
   - Continuous CI checks scan the bundle and source trees for administrative keys, PayPal secrets, and `localStorage` persistence, ensuring zero credentials enter the client bundle.
2. **Strict Production Startup Validation (`validate_production_configuration`):**
   - In production (`APP_ENV=production`), the application refuses to start up (raising `RuntimeError`) if:
     - `MANDATE_SIGNING_KEY` is missing, invalid hex, or left at the insecure default (`_DEV_KEY` or `0` * 64).
     - `ADMIN_API_KEY` is missing or left at the dev default (`admin_super_secret_test_key`).
     - `CSRF_SECRET` or `SESSION_SECRET` are left at development defaults.
3. **Telemetry & Public Key Boundaries:**
   - `GET /api/health` exposes key provenance (`key_source: "env" | "generated"`), database type, and worker counts, but is rigorously tested to never leak secret strings or key values.
   - `GET /api/mandate/public-key` exposes only the 32-byte Ed25519 public key in hex format for client-side signature verification; the private scalar is never exposed.
   - One-time human approval tokens are never stored in raw form in the database; only their SHA-256 digests (`token_hash`) are persisted, preventing token exfiltration from database dumps.
4. **Configuration Template Hygiene:**
   - Example configuration files (`.env.example`) must contain placeholder strings only (`your_paypal_client_secret_here`). Live sandbox credentials must strictly reside in `.gitignore` files (`backend/.env`).

---

## 10. Remaining Known Limitations & Operational Considerations

To maintain full transparency, the following technical and operational limitations are documented:

1. **SQLite Concurrency & Multi-Worker Deployments:**
   - The primary sandbox database uses SQLite with WAL mode (`aiosqlite`).
   - While SQLite supports high-concurrency readers, write operations require serial table-level/database-level locking.
   - If deploying with multiple Uvicorn workers (`WEB_CONCURRENCY > 1`) on ephemeral filesystems, the server logs a warning. For multi-node horizontal production scale, PostgreSQL should replace SQLite.
2. **PayPal Sandbox Latency:**
   - Live calls to PayPal Sandbox Orders v2 (`/v2/checkout/orders`) take between **1.2s and 4.5s** depending on upstream sandbox traffic.
   - Gateway timeout tolerances are set to 15 seconds to accommodate sandbox variability.
3. **Channel3 Search Rate Quotas:**
   - Real catalog lookups via Channel3 utilize an in-memory TTL cache (default 3600s) and daily quotas (`GLOBAL_CHANNEL3_DAILY_CAP = 250`).
   - If the external Channel3 quota is exhausted, the gateway falls back gracefully to cached high-fidelity catalog fixtures (`app/fixtures.py`).
4. **Physical Logistics / Fulfillment Blindness:**
   - As documented in Section 6, the firewall verifies digital specifications, merchant domains, and budget limits before settlement. It cannot verify warehouse inventory authenticity, supply chain integrity, or shipping transit conditions.
5. **Human Approval Channel Delivery Reliance:**
   - High-value human approvals depend on Telegram webhooks or UI notifications. If Telegram Bot API is unconfigured, human approvals must be accessed directly via the web dashboard or generated approval links.

