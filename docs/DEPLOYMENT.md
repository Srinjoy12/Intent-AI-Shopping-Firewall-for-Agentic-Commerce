# Intent AI Shopping Firewall — Production Deployment Guide

This guide provides step-by-step instructions for deploying the Intent AI Shopping Firewall to production environments (such as Render, Fly.io, Railway, AWS ECS, or bare-metal VPS).

---

## 1. Environment Variables Configuration

Intent requires specific secrets and environment parameters to guarantee cryptographic integrity and access control. In production (`APP_ENV=production`), the application enforces **startup refusal** if weak or default keys are detected.

### Core Variables

| Variable | Required? | Production Invariant | Description |
| :--- | :---: | :--- | :--- |
| `APP_ENV` | Yes | `production` | Enables production security checks (refuses dev fallback keys). |
| `ADMIN_API_KEY` | Yes | High-entropy secret | Secret token for administrative access, policy creation, and the global kill-switch. Passed via `X-Admin-Key` header. |
| `MANDATE_SIGNING_KEY` | Yes | 64-hex char Ed25519 seed | 32-byte private key seed for Ed25519 buyer mandate cryptographic signatures. (In development, an ephemeral key is generated on boot). |
| `PAYPAL_CLIENT_ID` | Yes | Valid PayPal Client ID | PayPal REST API credential (Sandbox or Live). |
| `PAYPAL_CLIENT_SECRET` | Yes | Valid PayPal Secret | PayPal REST API secret credential. |
| `PAYPAL_MODE` | Yes | `sandbox` or `live` | Determines PayPal API base URL (`api-m.sandbox.paypal.com` vs `api-m.paypal.com`). |
| `PAYPAL_WEBHOOK_ID` | Yes | PayPal Webhook ID | 17-character Webhook ID registered in PayPal Developer Dashboard for cryptographic signature verification. |
| `CHANNEL3_API_KEY` | Optional | API token | Channel3 catalog access key for live merchant catalog ground truth. If omitted, deterministic fixture catalog is used. |
| `DATABASE_PATH` | Yes | `/var/data/intent.db` | Path to persistent SQLite database file on persistent block storage. |
| `PUBLIC_BASE_URL` | Recommended | `https://your-domain.com` | Base URL used for constructing 1-click supervisor approval links. |
| `CSRF_SECRET` | Recommended | High-entropy secret | Secret for stateless CSRF HMAC validation. |
| `SESSION_SECRET` | Recommended | High-entropy secret | Secret for signing demo sandbox session cookies. |

> [!CAUTION]
> **Production Startup Refusal**: When `APP_ENV=production`, if `ADMIN_API_KEY` or `MANDATE_SIGNING_KEY` are missing or match known dev values (e.g. `admin_super_secret_test_key`), the server will immediately abort startup with an exit code of 1.

---

## 2. Persistent Disk Requirement

Intent persists cryptographic mandates, atomic headroom reservations, and the sequential SHA-256 audit ledger in SQLite. Because container deployments often have ephemeral filesystems, a **persistent disk volume** must be mounted.

### Render Configuration (`render.yaml`)

```yaml
services:
  - type: web
    name: intent-firewall
    env: python
    buildCommand: "pip install -r backend/requirements.txt && cd frontend && npm install && npm run build"
    startCommand: "cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
    disk:
      name: intent-data
      mountPath: /var/data
      sizeGB: 1
    envVars:
      - key: DATABASE_PATH
        value: /var/data/intent.db
      - key: APP_ENV
        value: production
      - key: WEB_CONCURRENCY
        value: "1"
```

### Docker Volume Mounting

```bash
# Create persistent volume
docker volume create intent_data

# Run container with volume mounted to /var/data
docker run -d \
  -p 8000:8000 \
  -v intent_data:/var/data \
  -e DATABASE_PATH=/var/data/intent.db \
  -e APP_ENV=production \
  --name intent-firewall \
  intent-firewall:latest
```

---

## 3. The Single-Worker Concurrency Invariant

Intent guarantees zero race conditions on daily budget spending limits and sequential audit hash chaining via **in-memory mutexes combined with SQLite ACID transactions** (`BEGIN IMMEDIATE`).

- **The Invariant**: When deployed with SQLite, the application **must run with exactly one worker process** (`--workers 1` or `WEB_CONCURRENCY=1`).
- **Why**: SQLite supports concurrent readers but serializes writes. In-memory locks coordinate async tasks within the process, while `BEGIN IMMEDIATE` guarantees database transaction serialization. Multiple separate OS processes running SQLite without a centralized lock server could encounter lock contention or audit sequence collisions.
- **Horizontal Scaling**: If multi-process clustering or multi-instance autoscaling is required, set `DATABASE_URL=postgresql://user:password@host:5432/dbname` to migrate the state and ledger to PostgreSQL.

---

## 4. PayPal Webhook Registration

To track asynchronous payment events (captures, refunds, disputes) and anchor them to the tamper-evident audit ledger, register a webhook in the PayPal Developer Dashboard.

### Step-by-Step Registration:

1. **Log in** to the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/).
2. Select your App under **Apps & Credentials** (Sandbox or Live).
3. Scroll to **Webhooks** and click **Add Webhook**.
4. Enter the **Webhook URL**:
   ```text
   https://<your-deployed-domain>/api/paypal/webhook
   ```
5. Select the following **Event Types**:
   - `PAYMENT.CAPTURE.COMPLETED` — Commits headroom reservation to `COMMITTED`.
   - `PAYMENT.CAPTURE.REFUNDED` — Restores headroom to consumer budget window.
   - `PAYMENT.CAPTURE.DENIED` — Releases reserved headroom on failure.
   - `CHECKOUT.ORDER.APPROVED` — Tracks buyer approval state.
6. Click **Save** and copy the generated **Webhook ID** (e.g., `4JH89234KL123456T`).
7. Set the `PAYPAL_WEBHOOK_ID` environment variable in your production deployment settings.

### Cryptographic Verification & Audit Anchoring Protocol:
- **Header Verification**: Incoming webhooks are verified against PayPal's certificate and signature headers (`PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-SIG`, `PAYPAL-TRANSMISSION-TIME`).
- **Replay Protection**: Webhook transmission IDs are recorded in the `processed_webhooks` table; duplicate deliveries are safely ignored with `200 OK`.
- **Ledger Anchoring**: During order creation, the SHA-256 `event_hash` of the local headroom reservation is injected into `purchase_units[0].custom_id`. When PayPal emits `PAYMENT.CAPTURE.COMPLETED`, the incoming payload's `custom_id` cryptographically anchors the payment back to the exact local reservation block.

---

## 5. Health Check & Telemetry

Production monitoring services (Render health checks, Datadog, AWS Route53) should poll the health endpoint:

```http
GET /api/health
```

### Sample Response (`200 OK`):

```json
{
  "status": "HEALTHY",
  "version": "1.0.0",
  "environment": "production",
  "database": {
    "status": "connected",
    "path": "/var/data/intent.db",
    "audit_events_count": 1420
  },
  "signing_key": {
    "algorithm": "Ed25519",
    "public_key_hex": "4a7b9c...",
    "persistent": true
  },
  "settlement": {
    "paypal_configured": true,
    "paypal_mode": "sandbox",
    "webhook_configured": true
  },
  "audit_chain": {
    "valid": true,
    "head_seq": 1420,
    "head_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
}
```

### Startup Self-Check:
During application boot, Intent automatically walks the SHA-256 audit chain from the genesis block (`0000...0000`) to the current tip. If any historical record, timestamp, or payload was tampered with while the service was offline, the health check reports `DEGRADED` or startup halts.

### Secrets Protection:
The health check endpoint exposes system status, key IDs, and audit head hashes, but **never exposes private keys, client secrets, or auth tokens**.
