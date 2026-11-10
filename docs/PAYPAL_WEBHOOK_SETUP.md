# PayPal Sandbox Webhook Setup & Audit Chain Anchoring Guide

This guide describes how to register and configure webhooks in the PayPal Developer Sandbox dashboard for the **Intent AI Gateway**, and how cryptographic audit chain anchoring guarantees end-to-end payment integrity.

---

## 1. Overview: Why Webhooks & Audit Anchoring?

1. **Cryptographic Anchoring**: When Intent creates a PayPal order, it embeds the SHA-256 `event_hash` of the `RESERVATION_CREATED` audit event into `purchase_units[0].custom_id` (fits within PayPal's 127-character limit) and the `attempt_id` into `purchase_units[0].invoice_id`. This creates an immutable, verifiable link between the PayPal ledger and Intent's local hash-chained audit trail.
2. **Asynchronous Webhook Settlement**: While synchronous transactions capture immediately, asynchronous events (e.g. buyer disputes, supervisor portal approvals, sandbox refunds, bank settlement failures) emit webhooks.
3. **Budget Invariant Enforcement**:
   - `PAYMENT.CAPTURE.COMPLETED`: Commits the in-memory/SQLite budget reservation.
   - `PAYMENT.CAPTURE.REFUNDED`: Transitions the reservation to `RELEASED`, immediately restoring daily/weekly headroom.
   - `PAYMENT.CAPTURE.DENIED`: Releases the reserved budget back to the user's spending pool.
4. **Idempotency & Fraud Protection**: Every webhook is verified against PayPal's `POST /v1/notifications/verify-webhook-signature` API using `PAYPAL_WEBHOOK_ID`, and deduplicated by `event_id` to prevent replay attacks.

---

## 2. Step-by-Step: Registering the Webhook in PayPal Sandbox

### Step 1: Open PayPal Developer Dashboard
1. Log in to [developer.paypal.com](https://developer.paypal.com/dashboard).
2. Ensure the environment toggle is set to **Sandbox**.

### Step 2: Select Your REST App
1. Go to **Apps & Credentials**.
2. Under **REST API Apps**, click on your application (e.g., `Default Application` or your custom hackathon app).

### Step 3: Add Webhook
1. Scroll down to the **Webhooks** section.
2. Click **Add Webhook**.
3. In **Webhook URL**, enter your public deployment URL or local tunnel:
   - **Production / Render**: `https://<your-render-app>.onrender.com/api/paypal/webhook`
   - **Local Testing (ngrok/Cloudflare)**: `https://<your-tunnel-subdomain>.ngrok-free.app/api/paypal/webhook`
4. Under **Event types**, select the following 3 events:
   - `Payment capture completed` (`PAYMENT.CAPTURE.COMPLETED`)
   - `Payment capture refunded` (`PAYMENT.CAPTURE.REFUNDED`)
   - `Payment capture denied` (`PAYMENT.CAPTURE.DENIED`)
5. Click **Save**.

### Step 4: Copy the Webhook ID
1. Once saved, PayPal displays a **Webhook ID** (e.g. `9AB12345CD67890EF`).
2. Copy this value and add it to your environment configuration:
   ```env
   PAYPAL_WEBHOOK_ID=9AB12345CD67890EF
   ```

---

## 3. Webhook Signature Verification Protocol

When PayPal sends a webhook notification to `POST /api/paypal/webhook`, Intent verifies the authenticity of the message before processing:

```
┌─────────────────┐             ┌─────────────────────┐             ┌─────────────────────┐
│ PayPal Webhook  │── POST ────>│  Intent AI Gateway  │── Verify ──>│  PayPal API:        │
│ Dispatcher      │             │  /api/paypal/webhook│             │  verify-webhook-sig │
└─────────────────┘             └─────────────────────┘             └─────────────────────┘
                                           │                                   │
                                           │<──────── SUCCESS / FAILURE ───────┘
                                           │
                                ┌──────────┴──────────┐
                                │ Valid?              │
                                ├──────────┬──────────┤
                                │ YES      │ NO       │
                                ▼          ▼          ▼
                           Idempotent   HTTP 400
                           Execution    (Rejected)
```

The gateway extracts the following 5 cryptographic headers:
- `PAYPAL-AUTH-ALGO` (e.g. `SHA256withRSA`)
- `PAYPAL-CERT-URL`
- `PAYPAL-TRANSMISSION-ID`
- `PAYPAL-TRANSMISSION-SIG`
- `PAYPAL-TRANSMISSION-TIME`

These headers, along with the raw payload body and `PAYPAL_WEBHOOK_ID`, are transmitted to PayPal's verification endpoint:
`POST https://api-m.sandbox.paypal.com/v1/notifications/verify-webhook-signature`

If the response status is not `SUCCESS` or if headers are missing, Intent rejects the request with **HTTP 400**.

---

## 4. Idempotency & State Mutation Mechanics

| Webhook Event Type | Attempt Status | Budget Reservation Status | Audit Event Logged |
|---|---|---|---|
| `PAYMENT.CAPTURE.COMPLETED` | `CAPTURED` | `COMMITTED` | `PAYPAL_WEBHOOK_COMPLETED` |
| `PAYMENT.CAPTURE.REFUNDED` | `REFUNDED` | `RELEASED` (Restores Headroom) | `PAYPAL_WEBHOOK_REFUNDED` |
| `PAYMENT.CAPTURE.DENIED` | `DENIED` | `RELEASED` (Restores Headroom) | `PAYPAL_WEBHOOK_DENIED` |

### Replay Attack Prevention
All incoming event IDs (`WH-...`) are recorded in the SQLite table `processed_webhooks`. If a duplicate notification arrives with an already-processed `event_id`, Intent immediately returns:
```json
{
  "status": "already_processed",
  "event_id": "WH-...",
  "event_type": "PAYMENT.CAPTURE.COMPLETED"
}
```
with **HTTP 200** without mutating reservations or appending duplicate audit events.

---

## 5. Audit Anchoring Endpoints

### 1. List Order Anchors: `GET /api/audit/anchors`
Returns a list of recent orders with their anchored SHA-256 audit hashes and verification status:
```json
[
  {
    "order_id": "9AB12345CD67890EF",
    "capture_id": "7GH12345JK67890LM",
    "attempt_id": "att_f8b2c4e1",
    "mandate_id": "mandate_01",
    "anchored_hash": "a1b2c3d4e5f6...7890abcdef",
    "invoice_id": "att_f8b2c4e1",
    "status": "CAPTURED",
    "matches_chain": true,
    "created_at": "2026-11-07T12:00:00Z"
  }
]
```

### 2. Verify Order Anchor: `GET /api/audit/anchors/{order_id}/verify`
Fetches the order live from the PayPal Sandbox API (`GET /v2/checkout/orders/{order_id}`), extracts `purchase_units[0].custom_id`, and cryptographically confirms that this hash exists in Intent's sequential audit chain:
```json
{
  "valid": true,
  "order_id": "9AB12345CD67890EF",
  "anchored_hash": "a1b2c3d4e5f6...7890abcdef",
  "invoice_id": "att_f8b2c4e1",
  "matches_chain": true,
  "event_seq": 42,
  "event_type": "RESERVATION_CREATED",
  "event_timestamp": "2026-11-07T11:59:58Z",
  "attempt_id": "att_f8b2c4e1"
}
```
If the anchor was tampered with in PayPal or was not issued by Intent, `matches_chain: false` is returned with diagnostic details.

