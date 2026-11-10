# Production Persistence, Deployment & Key Management Guide

## 1. Overview
Intent acts as an authoritative, cryptographic firewall between untrusted LLMs and payment execution (PayPal Sandbox). To guarantee tamper-evident auditability, single-use approval integrity, and budget invariants, production environments must observe strict persistence and key management constraints.

---

## 2. Persistence & Storage Architecture

### Persistent Disk Requirement
- **Why It's Critical**: The application writes immutable Ed25519-signed mandates, an append-only SHA-256 audit ledger, and atomic budget reservations to SQLite (`DATABASE_PATH`). In an ephemeral filesystem (e.g., standard stateless serverless or unmounted containers), a container restart obliterates all issued mandates and previous audit chain entries. Any subsequent verification of previous receipts or exported chains would fail against a fresh genesis hash.
- **Production Setup**:
  - Mount a persistent block volume / SSD at `/var/data` (configured in `render.yaml` with a 1 GB disk).
  - Configure `DATABASE_PATH=/var/data/intent.db` (or set `DATABASE_URL=sqlite:////var/data/intent.db`).
  - For horizontally scaled multi-node clusters, replace SQLite with PostgreSQL (`DATABASE_URL=postgresql://user:pass@host:5432/dbname`).

---

## 3. Concurrency & Single-Worker Enforcement

### The SQLite Concurrency Invariant
- **Invariant**: Intent utilizes in-memory mutexes combined with SQLite ACID transactions to guarantee that cumulative daily/weekly spending caps cannot be exceeded via concurrent race conditions, and that every audit log entry chains directly to the SHA-256 digest of the immediately preceding event.
- **Requirement**: When running with SQLite, `WEB_CONCURRENCY` (or `WORKERS`) **must be set to 1**.
- **Enforcement**: If the application detects `WEB_CONCURRENCY > 1` alongside a SQLite database, it emits a prominent warning at startup:
  ```
  ⚠️ [CONCURRENCY WARNING] WEB_CONCURRENCY=X > 1 with SQLite database.
  SQLite in-memory budget reservation locks and audit chain sequential hashing
  require single-worker operation (WEB_CONCURRENCY=1) to prevent race conditions.
  For multi-worker deployments, configure PostgreSQL via DATABASE_URL.
  ```

---

## 4. Key Management & Production Refusal

When `APP_ENV=production`, the application performs strict pre-flight validation during lifespan startup. If any critical secret is missing or set to insecure development defaults, the process aborts immediately with a descriptive `RuntimeError`:

| Environment Variable | Production Requirement | Generation Command |
|---|---|---|
| `MANDATE_SIGNING_KEY` | 32-byte Ed25519 private seed (64 hex chars). Cannot be dev placeholder or all zeros. | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_API_KEY` | Strong secret (>= 16 chars). Cannot be `admin_super_secret_test_key` or prefix `dev_`/`test_`. | `openssl rand -hex 32` |
| `CSRF_SECRET` | Stateless HMAC-SHA256 secret. Cannot be dev default. | `openssl rand -hex 32` |
| `SESSION_SECRET` | Demo sandbox cookie signature secret. Cannot be dev default. | `openssl rand -hex 32` |

> In `APP_ENV=development`, if `MANDATE_SIGNING_KEY` is omitted, the gateway auto-generates an ephemeral Ed25519 keypair for the session and logs a prominent warning.

---

## 5. Health Endpoint Telemetry (`GET /api/health`)

The health endpoint provides visibility into the operational mode and persistence state **without ever revealing secret values or private keys**:

```json
{
  "status": "ok",
  "channel3_configured": true,
  "paypal_configured": true,
  "llm_provider": "stub",
  "app_mode": "demo",
  "app_env": "production",
  "key_source": "env",
  "database_type": "sqlite",
  "persistent_storage": true,
  "worker_count": 1
}
```

### Telemetry Field Definitions
- `key_source`: `"env"` if loaded from environment configuration; `"generated"` if created ephemerally.
- `database_type`: `"sqlite"` or `"postgresql"`.
- `persistent_storage`: Boolean indicating whether the database is located on persistent storage (e.g. mounted disk) vs ephemeral `/tmp` or `:memory:`.
- `worker_count`: Number of concurrency workers active.

---

## 6. Startup Audit Chain Self-Check

At every boot cycle, Intent loads the entire historical audit ledger and executes `verify_audit_chain()`:
1. Recomputes the SHA-256 hash of each event payload `(index, timestamp, event_type, payload_json, previous_hash)`.
2. Asserts strict hash chaining from `GENESIS_HASH` to the current ledger tip.
3. Logs verification status:
   - `Startup audit chain verified: VALID (length=N, head=...)` on success.
   - `Startup audit chain verification FAILED: ...` if any log entry was tampered with or corrupted while the service was stopped.

---

## 7. One-Click Deployment (Render / Docker)

### Option A: Render Blueprint (`render.yaml`)
1. Connect repository to Render.
2. Select **New > Blueprint**.
3. Render reads `render.yaml`:
   - Builds multi-stage `Dockerfile` (Node 20 frontend + Python 3.12 backend).
   - Provisions a 1 GB SSD disk mounted to `/var/data`.
   - Auto-generates cryptographic keys (`MANDATE_SIGNING_KEY`, `ADMIN_API_KEY`, etc.).
   - Connects `/api/health` keep-alive check.

### Option B: Docker Container
```bash
# Build multi-stage image
docker build -t intent-firewall:latest .

# Run with persistent volume mount
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/var/data \
  -e APP_ENV=production \
  -e MANDATE_SIGNING_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -e ADMIN_API_KEY=$(openssl rand -hex 32) \
  -e CSRF_SECRET=$(openssl rand -hex 32) \
  -e SESSION_SECRET=$(openssl rand -hex 32) \
  -e PAYPAL_CLIENT_ID=your_paypal_client_id \
  -e PAYPAL_CLIENT_SECRET=your_paypal_client_secret \
  intent-firewall:latest
```

