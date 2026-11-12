# Intent AI Gateway — Endpoint Authentication & State Mutation Matrix

This document defines the authorization requirements and state mutation behavior for every endpoint exposed by the Intent AI Gateway application.

Enforcement values and policies are strictly bound to cryptographically signed mandates (Ed25519 + SHA-256 canonical policy hash). Modifying enforcement policies or mandates in place without a cryptographic signature is disallowed.

---

## Endpoint Authentication Matrix

| Method | Path | Auth Required | Mutates State | Description & Security Controls |
| :--- | :--- | :--- | :---: | :--- |
| **GET** | `/api/health` | None | No | System health check, Channel3 and PayPal configuration status. |
| **GET** | `/api/policy` | None | No | Returns the active mandate's verified values, cryptographic signature status, and `policy_hash`. |
| **PUT** | `/api/policy` | Admin key | **Yes** | Constructs, Ed25519-signs, and persists a **NEW** cryptographic mandate. In-place unauthenticated mutation is eliminated. |
| **GET** | `/api/mandate/public-key` | None | No | Exposes the system's Ed25519 public key in hex format for offline client verification. |
| **POST** | `/api/mandates` | Admin key | **Yes** | Issues, Ed25519-signs, and stores a new mandate with canonical SHA-256 `policy_hash` and audit logging. |
| **GET** | `/api/mandates/{mandate_id}` | None | No | Retrieves stored mandate details and status by mandate ID. |
| **POST** | `/api/mandates/{mandate_id}/revoke` | Admin key | **Yes** | Revokes an existing mandate and appends a `MANDATE_REVOKED` audit event. |
| **GET** | `/api/audit/verify` | None | No | Walks the SQLite audit log and cryptographically validates SHA-256 hash-chain continuity. |
| **GET** | `/api/audit/export` | Admin key | No | Exports full hash-chained audit manifest signed with the system's Ed25519 private key. |
| **GET** | `/api/audit/anchors` | None | No | Lists captured orders with PayPal order ID, capture ID, anchored SHA-256 event hash, and chain match status. |
| **GET** | `/api/audit/anchors/{order_id}/verify` | None | No | Fetches live order from PayPal sandbox API and confirms `custom_id` matches the audit chain. |
| **POST** | `/api/paypal/webhook` | Webhook Sig | **Yes** | Idempotent webhook listener for `PAYMENT.CAPTURE.COMPLETED`, `REFUNDED`, `DENIED`. Verifies signature via PayPal API; updates reservation & audit ledger. |
| **GET** | `/api/benchmark/latest` | None | No | Retrieves latest adversarial benchmark evaluation results (72 cases, 0% bypass). |
| **POST** | `/api/agents/{agent_id}/pause` | Admin key | **Yes** | Emergency kill switch: immediately blocks an agent from submitting intent or payments. |
| **POST** | `/api/agents/{agent_id}/resume` | Admin key | **Yes** | Resumes a previously paused agent. |
| **GET** | `/api/agents/{agent_id}/status` | None | No | Checks operational status and pause/active state of an agent. |
| **GET** | `/api/approvals/action` | None | No | Read-only confirmation page with details & countdown. Stateless CSRF generated; **zero database writes**. |
| **POST** | `/api/approvals/action` | Session | **Yes** | Consumes one-time crypto approval token + HMAC-SHA256 CSRF token. Resolves order and redirects (303). |
| **GET** | `/api/approvals/status/{approval_id}` | None | No | Read-only result landing page following 303 PRG redirect; safe to refresh without resubmission risk. |
| **POST** | `/api/approvals/{approval_id}/resolve` | Admin key | **Yes** | Admin dashboard direct approval/denial resolution by approval ID. |
| **GET** | `/api/approvals/pending` | None | No | Lists pending human supervisor approval requests awaiting action. |
| **GET** | `/api/presets` | None | No | Returns curated red-team prompt injection presets for attack arena. |
| **GET** | `/api/products/fixtures` | None | No | Returns pre-cached catalog fixtures (costs 0 external API credits). |
| **GET** | `/api/products/search` | None | No | Searches catalog via Channel3 or falls back to local fixture catalog. |
| **GET** | `/api/products/{product_id}` | None | No | Retrieves normalized product details and structured attributes. |
| **POST** | `/api/verify-and-pay` | Agent key | **Yes** | Primary firewall gate: enforces 4 deterministic rules under signed mandate, reserves budget, settles via PayPal. |
| **POST** | `/api/run-preset/{preset_id}` | None | **Yes** | Test harness endpoint: evaluates red-team attack preset against the signed mandate. |
| **POST** | `/api/agent/self-heal` | None | **Yes** | Interactive self-healing simulation: evaluates Turn 1 injection block and Turn 2 remediation. |
| **POST** | `/api/agent/shop` | None | **Yes** | Shopping agent loop simulation executing intent against the deterministic gateway. |
| **POST** | `/api/paypal/capture/{order_id}` | Admin key | **Yes** | Captures approved PayPal Sandbox order, commits budget reservation, and records audit event. |
| **POST** | `/api/paypal/refund/{capture_id}` | Admin key | **Yes** | Refunds PayPal Sandbox capture, restores budget headroom, and records audit events. |
| **GET** | `/api/rate-limit-status` | None | No | Returns daily call counters, rate limiter state, and circuit-breaker quotas. |
| **GET** | `/api/attempts` | None | No | Fetches recent purchase attempts and audit event hashes for AG Grid analytics ledger. |
| **GET** | `/api/analytics` | None | No | Aggregates summary statistics: dollars captured, dollars prevented, violation breakdown. |
| **GET** | `/api/demo/session` | Session | No | Returns caller's isolated sandbox session metadata, agent ID, and mandate ID. |
| **GET** | `/api/demo/mandate` | Session | No | Returns verified mandate and policy hash belonging strictly to caller's session. |
| **POST** | `/api/demo/verify-and-pay` | Session | **Yes** | Executes 4-rule gate and settlement strictly bound to caller's sandbox agent & mandate. |
| **POST** | `/api/demo/run-preset/{preset_id}` | Session | **Yes** | Executes red-team preset bound to caller's sandbox; carries session tag. |
| **POST** | `/api/demo/self-heal` | Session | **Yes** | 2-turn self-healing simulation bound strictly to caller's sandbox. |
| **POST** | `/api/demo/pause` | Session | **Yes** | Pauses ONLY caller's session agent (zero impact on other sessions or admin). |
| **POST** | `/api/demo/resume` | Session | **Yes** | Resumes ONLY caller's session agent. |
| **GET** | `/api/demo/agent-status` | Session | No | Returns kill-switch pause status for caller's session agent. |
| **GET** | `/api/demo/approvals/pending` | Session | No | Lists pending approvals belonging strictly to caller's session. |
| **POST** | `/api/demo/approvals/{approval_id}/resolve` | Session | **Yes** | Resolves approval request belonging strictly to caller's session (cross-session rejected with 403). |
| **POST** | `/api/demo/capture/{order_id}` | Session | **Yes** | Captures PayPal order belonging strictly to caller's session (cross-session rejected with 403). |
| **POST** | `/api/demo/refund/{capture_id}` | Session | **Yes** | Refunds PayPal capture belonging strictly to caller's session (cross-session rejected with 403). |
| **GET** | `/api/demo/attempts` | Session | No | Returns past verification attempts strictly for caller's session. |
| **GET** | `/api/demo/analytics` | Session | No | Computes aggregate analytics strictly for caller's session. |
| **POST** | `/api/demo/reset` | Session | **Yes** | Resets visitor sandbox session and issues fresh session cookie. |


---

## Authentication Schemes

1. **None (Public / Read-Only)**
   - Read-only queries for catalog, public key, health, benchmarks, analytics, and confirmation rendering.
   - Confirmation page (`GET /api/approvals/action`) receives a one-time random token via URL parameter, strictly displays details, and generates a stateless HMAC-SHA256 CSRF token without performing database writes.

2. **Agent Key (`X-Agent-Key`)**
   - Autonomous purchasing agents must supply an active agent API key.
   - Validated via constant-time SHA-256 comparison against `agent_keys` table.
   - Calling agent ID is strictly validated against `mandate.agent_id` (`MANDATE_AGENT_MISMATCH` check).

3. **Admin Key (`X-Admin-Key` or `Authorization: Bearer <key>`)**
   - High-privilege administrative operations: creating/revoking mandates, updating policy (issuing new signed mandates), pausing/resuming agents (kill switch), capturing payments, and issuing refunds.
   - Enforced by `require_admin_key` dependency via constant-time comparison against `ADMIN_API_KEY`.
   - In public demo mode, browser clients NEVER receive or hold admin keys.

4. **Single-Use Crypto Token + CSRF (`POST /api/approvals/action`)**
   - Human supervisor approval actions require:
     - A 256-bit cryptographic single-use URL-safe token.
     - A stateless CSRF token: `HMAC-SHA256(CSRF_SECRET, approval_id || token_hash || expires_at)` verified in constant time.
   - Consumed exactly once; token reuse returns HTTP 409 `TOKEN_ALREADY_USED`.
   - On completion, redirects (HTTP 303) to `/api/approvals/status/{approval_id}` so page refreshes cannot re-trigger actions.

5. **Demo Session Sandbox (`intent_session` Cookie)**
   - Used for public interactive evaluation without exposing admin or agent keys.
   - Signed HttpOnly, `SameSite=Lax` cookie derived via `HMAC-SHA256(SESSION_SECRET, session_id)`.
   - Provisions a multi-tenant sandbox with a dedicated agent ID, dedicated signed mandate, and 2-hour TTL.
   - Enforces a 30 requests/hour rate limit per session (isolated across users).
   - Strict session isolation: `/api/demo/*` routes reject reading or modifying another session's resources.

6. **PayPal Webhook Signature Verification (`POST /api/paypal/webhook`)**
   - Authenticated via PayPal's asynchronous signature verification endpoint (`/v1/notifications/verify-webhook-signature`).
   - Requires valid `PAYPAL_WEBHOOK_ID` matching the incoming PayPal signature headers (`paypal-auth-algo`, `paypal-cert-url`, `paypal-transmission-id`, `paypal-transmission-sig`, `paypal-transmission-time`).
   - Idempotently prevents duplicate event replays via `paypal_webhook_events` tracking table.

7. **Simulation & Test Harness Endpoints (Public Simulation)**
   - `/api/run-preset/{preset_id}`, `/api/agent/self-heal`, `/api/agent/shop`
   - These are public interactive simulation endpoints designed for demonstration and developer red-teaming.
   - They execute pure-code evaluation logic against catalog fixtures and record attempt telemetry. They do NOT capture funds or bypass signed mandate rules. In interactive demo mode, the web frontend calls their session-scoped counterparts (`/api/demo/run-preset/...`, `/api/demo/self-heal`).

---

## Automated Security Regression Guards

Route security is rigorously enforced continuously across two automated layers:
1. **Route Security Regression Test (`tests/test_mandate.py::test_route_security_regression_guard_all_mutating_endpoints_require_auth`):**
   - Programmatically inspects all registered FastAPI routes during every test run.
   - Confirms that every mutating endpoint that alters policy, mandates, agent status, approvals, captures, or refunds possesses either a strict `require_admin_key` dependency or cryptographic session/token verification.
   - Status: **PASSED (100% route coverage verified)**.

2. **Scripted Multi-Tenant End-to-End Isolation Test (`scripts/verify_demo_isolation_e2e.py` / `test_demo_sandbox.py`):**
   - Simulates two concurrent visitor sessions (Alice and Bob) and verifies that Session A cannot pause, resume, read attempts, view pending approvals, resolve approvals, or refund orders belonging to Session B (HTTP 403 Forbidden).
   - Status: **PASSED (Zero cross-session data leaks or unauthorized mutations)**.

