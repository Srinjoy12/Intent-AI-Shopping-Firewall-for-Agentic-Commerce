# Intent AI Shopping Firewall — System Architecture & Technical Specifications

> **Core Invariant**: Untrusted LLM agents must never possess unattended authorization to execute financial transactions. Intent operates as a zero-trust, deterministic server-side gateway that verifies merchant ground truth, validates structured product attributes fail-closed, enforces cryptographic spending mandates, and anchors every PayPal transaction to an immutable, append-only SHA-256 audit chain before funds can move.

---

## 1. High-Level Architecture Overview

Intent sits strictly between the client/agent layer and third-party financial and commerce infrastructure:

```
┌────────────────────────────────────────────────────────┐
│             Untrusted Client / LLM Agent               │
│   (Compromised by Prompt Injection / Hallucinations)   │
└──────────────────────────┬─────────────────────────────┘
                           │ Submits 4 Intent Parameters:
                           │ { policy_id, product_id, merchant_domain, quantity }
                           ▼
┌────────────────────────────────────────────────────────┐
│       Intent Deterministic Firewall (FastAPI)          │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 1. Mandate & Session Validation                  │  │
│  │    • Ed25519 cryptographic signature check        │  │
│  │    • Multi-tenant sandbox session isolation      │  │
│  │    • Kill-switch verification                    │  │
│  └──────────────────────────┬───────────────────────┘  │
│                             ▼                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 2. 4-Rule Deterministic Verification Engine       │  │
│  │    • Rule 1: Merchant Domain & Offer (Channel3)  │  │
│  │    • Rule 2: Structured Attributes (Fail-Closed) │  │
│  │    • Rule 3: Quantity & Budget Caps              │  │
│  │    • Rule 4: Headroom Reservation & Routing      │  │
│  └──────────────────────────┬───────────────────────┘  │
│                             ▼                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 3. Settlement Router & Tamper-Evident Ledger     │  │
│  │    • Outcome A: <= $1,000 Auto-Capture           │  │
│  │    • Outcome B: > $1,000 Human Supervisor Hold   │  │
│  │    • Append-only SHA-256 hash-chained audit      │  │
│  └──────────────────────────┬───────────────────────┘  │
└─────────────────────────────┼──────────────────────────┘
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│ Channel3 Catalog API v1  │     │   PayPal Orders v2 API   │
│  100M+ Canonical Products│     │   Advanced Card Capture  │
└──────────────────────────┘     └──────────────────────────┘
```

---

## 2. The 4-Rule Deterministic Verification Engine

The gateway executes four sequential verification gates in pure Python (`backend/app/engine.py`). If any rule fails, the pipeline halts immediately, commits zero budget, creates no PayPal order, and returns structured JSON remediation feedback:

### Rule 1: Merchant Domain Allowlisting & Offer Availability
- **Purpose**: Prevent unauthorized vendor routing and domain-spoofing attacks (e.g., lookalike domains like `amzn-checkout.co`).
- **Mechanism**: The requested `merchant_domain` is checked against the mandate's allowed merchants and queried against Channel3 catalog ground truth (`https://api.trychannel3.com/v1`). If the merchant does not offer the SKU or the domain is not allowlisted, the transaction is rejected with `OFFER_UNAVAILABLE` or `UNAUTHORIZED_MERCHANT`.

### Rule 2: Structured Attribute Fail-Closed Validation
- **Purpose**: Defeat spec spoofing, misleading merchant copy, and hallucinated specifications.
- **Mechanism**: Product attributes (e.g., `ram: 16GB`, `storage: 512GB`) are verified against authoritative structured attributes returned by Channel3.
- **Fail-Closed Guarantee**: If an attribute specified in the user's mandate is missing, ambiguous, or unconfirmed in the catalog record, Intent **fails closed** (`UNVERIFIABLE_ATTRIBUTE`), preventing purchases based on assumptions.

### Rule 3: Quantity & Budget Invariants Math
- **Purpose**: Prevent cart inflation, hidden fee bypasses, and prompt injection quantity tampering.
- **Mechanism**: Evaluates:
  $$\text{Item Total} = \text{Unit Price} \times \text{Quantity}$$
  $$\text{Item Total} \le \text{Max Item Budget}$$
  $$\text{Quantity} \le \text{Max Quantity}$$
  $$\text{Cumulative Daily Spend} + \text{Item Total} \le \text{Daily Spending Limit}$$
  If any threshold is exceeded, the request is rejected with `BUDGET_EXCEEDED` or `MAX_QUANTITY_EXCEEDED` alongside exact numeric headroom calculations.

### Rule 4: Headroom Reservation & PayPal Settlement Routing
- **Purpose**: Atomically reserve spending headroom and route to appropriate settlement path.
- **Outcomes**:
  - **Outcome A (Autonomous Server-Side Capture)**: For subtotal $\le \$1,000.00$, single-call Advanced Card Processing capture (`intent: CAPTURE`) executes autonomously via PayPal Sandbox.
  - **Outcome B (1-Click Human Supervisor Approval)**: For high-value transactions $(\$1,000.00 < \text{subtotal} \le \text{Hard Ceiling})$, an order hold is created. A time-limited, cryptographic approval token is generated (`/api/approvals/action?token=...`). Funds move only after explicit human approval.

---

## 3. Cryptographic Buyer Mandates

To ensure non-repudiation and prevent policy tampering, Intent implements signed buyer contracts (`backend/app/mandate.py`):

1. **Ed25519 Keypair**: Generated at setup or loaded via `MANDATE_SIGNING_KEY`.
2. **Canonical Serialization**: Mandate parameters (policy ID, allowed domains, spending limits, required attributes, validity period) are serialized to canonical JSON (sorted keys, compact delimiters).
3. **Detached Signature**: The mandate payload is signed with Ed25519. Every incoming request must verify against the active public key before evaluation begins.
4. **Kill-Switch**: An authoritative, atomic kill-switch allows immediate policy revocation. Revoked policies reject all subsequent transaction requests.

---

## 4. Tamper-Evident SHA-256 Audit Ledger

Every transaction attempt, evaluation step, human approval decision, and PayPal event is recorded in an immutable audit ledger (`backend/app/audit.py`):

- **Hash-Chaining**: Each audit entry incorporates the SHA-256 digest of the immediately preceding event:
  $$\text{Hash}_n = \text{SHA256}(\text{Index}_n \parallel \text{Timestamp}_n \parallel \text{EventType}_n \parallel \text{Payload}_n \parallel \text{Hash}_{n-1})$$
- **Genesis Block**: Rooted in a deterministic `GENESIS_HASH`.
- **Startup Verification**: At every application boot cycle, the entire audit history is re-verified from genesis to the latest event tip. If any database record has been altered offline, startup halts with an integrity error.
- **Offline Export & Verification**: An Ed25519-signed manifest and SHA-256 event log can be exported and verified independently via `make verify-export`.

---

## 5. Persistence, Storage & Concurrency Architecture

### Persistent Disk Requirement
The gateway writes signed mandates, atomic budget reservations, and the sequential audit chain to SQLite (`DATABASE_PATH`). 
- **Production Deployment**: Mount a persistent block storage volume (e.g. `/var/data` configured in `render.yaml`).
- **Configuration**: `DATABASE_PATH=/var/data/intent.db` (or `DATABASE_URL=sqlite:////var/data/intent.db`).

### The Single-Worker Concurrency Invariant
- **Invariant**: Intent utilizes in-memory mutexes paired with SQLite ACID transactions to prevent race conditions during budget headroom reservations and audit chain hashing.
- **Requirement**: When running with SQLite, `WEB_CONCURRENCY` (or `WORKERS`) must be set to `1`.
- **Horizontal Scaling**: For multi-worker or multi-container clusters, configure PostgreSQL via `DATABASE_URL=postgresql://user:pass@host:5432/dbname`.

---

## 6. PayPal Webhook Setup & Audit Anchoring

### Cryptographic Anchoring
When Intent constructs a PayPal order:
1. The SHA-256 `event_hash` of the `RESERVATION_CREATED` audit event is embedded into `purchase_units[0].custom_id` (fits within PayPal's 127-character limit).
2. The `attempt_id` is embedded into `purchase_units[0].invoice_id`.

This creates a bidirectional, immutable link between PayPal's ledger and Intent's local audit trail.

### Webhook Event Handling
- `PAYMENT.CAPTURE.COMPLETED`: Commits the in-memory budget reservation to `COMMITTED`.
- `PAYMENT.CAPTURE.REFUNDED`: Transitions the reservation to `RELEASED`, immediately restoring consumer spending headroom.
- `PAYMENT.CAPTURE.DENIED`: Releases reserved budget back to the pool.

### Webhook Signature Verification Protocol
All incoming webhook dispatches to `POST /api/paypal/webhook` are validated against PayPal's `POST /v1/notifications/verify-webhook-signature` endpoint using the 5 standard transmission headers (`PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-SIG`, `PAYPAL-TRANSMISSION-TIME`) and `PAYPAL_WEBHOOK_ID`. Replays are prevented by deduplicating against the `processed_webhooks` table.

---

## 7. Key Management & Environment Configuration

| Variable | Environment | Description |
| :--- | :--- | :--- |
| `MANDATE_SIGNING_KEY` | Production | 32-byte Ed25519 private seed (64 hex characters). Auto-generated ephemeral key in development. |
| `ADMIN_API_KEY` | All | Bearer token required for administrative, policy-mutating, and kill-switch endpoints. |
| `CSRF_SECRET` | Production | Stateless HMAC-SHA256 secret for CSRF token generation. |
| `SESSION_SECRET` | Production | Secret for signing multi-tenant demo sandbox session cookies. |
| `PAYPAL_CLIENT_ID` | All | PayPal REST App Client ID (Sandbox or Production). |
| `PAYPAL_CLIENT_SECRET` | All | PayPal REST App Client Secret. |
| `PAYPAL_WEBHOOK_ID` | Optional | PayPal Webhook ID for webhook signature verification. |
| `CHANNEL3_API_KEY` | Optional | Channel3 API key for querying live 100M+ product catalog. |

Telemetry is accessible via `GET /api/health` without exposing secrets.
