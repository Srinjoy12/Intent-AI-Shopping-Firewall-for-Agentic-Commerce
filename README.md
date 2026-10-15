# Intent: AI Shopping Firewall

> Your AI agent can shop 100M+ real products for you on PayPal—with spending limits, quantities, and structured product attributes deterministically enforced before funds move.

**Built for the PayPal AI Hackathon: Build What's Next with PayPal and AI**

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Shopping    │────▶│  Intent Gateway  │────▶│  PayPal        │
│  LLM Agent  │     │  (4-Rule Engine)  │     │  Sandbox API   │
│             │     │                    │     │                │
│  Submits:   │     │  Pulls:           │     │  Creates:      │
│  product_id │     │  Channel3 catalog │     │  Orders        │
│  domain     │     │  structured_attrs │     │  Captures      │
│  quantity   │     │  offer.price      │     │  Refunds       │
└─────────────┘     └──────────────────┘     └────────────────┘
                           │
              Untrusted LLM NEVER sees
              prices, specs, or payment data
```

## Quick Start

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in your API keys
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings & env vars
│   │   ├── models.py            # Pydantic schemas
│   │   ├── engine.py            # 4-Rule Verification Engine
│   │   ├── channel3_client.py   # Channel3 SDK wrapper + caching
│   │   ├── paypal_client.py     # PayPal Sandbox API client
│   │   ├── llm_adapter.py       # Pluggable LLM adapter (stubbed)
│   │   ├── rate_limiter.py      # slowapi rate limits + circuit breaker
│   │   └── fixtures.py          # Pre-cached product fixtures
│   ├── requirements.txt
│   └── .env.example
├── frontend/                    # Vite + React
├── DESIGN.md
├── LICENSE                      # MIT
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
