# Prototype: AI Shop Assistant + PayPal Sandbox Checkout

Demo for the PayPal AI Hackathon 2026. A chat assistant for a fictional
local service business: it answers hours/prices, books appointments, and
collects a deposit through PayPal — then confirms the booking automatically.

## Run locally (no keys needed)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # mock mode works with no keys filled in
python3 app.py              # -> http://localhost:5000
```

Try this in the chat UI (or use the quick-reply chips):

1. "What are your hours?" / "How much is a full detail?"
2. "Book a full detail tomorrow 10am" → give your name when asked
3. "Pay deposit" → click the payment link
4. In mock mode, click **Simulate buyer approval** (the mock PayPal link
   is not a real order) → booking status flips to `confirmed`

Check state anytime: `GET /api/bookings`.

## Switch to the real PayPal sandbox

1. Create a sandbox app in your own PayPal Developer account and copy the
   Client ID / Secret into `.env` (never commit `.env` — it is gitignored).
2. Set `PAYPAL_MODE=sandbox` in `.env` and restart.
3. Approve the order with a PayPal sandbox buyer account; PayPal will
   redirect back to `/api/paypal/return`, which captures the order and
   confirms the booking.

## How it is built

| File | Role |
|---|---|
| `app.py` | Flask routes: chat, PayPal create/capture/return/webhook, bookings |
| `ai_agent.py` | Conversation layer: rule-based demo brain + pluggable `LLMClient` |
| `paypal_client.py` | PayPal Orders API v2 (mock mode + real sandbox mode) |
| `store.py` | In-memory bookings/orders (demo only; use a DB for a real product) |
| `templates/index.html` | Chat demo UI |

## Demo data

The shop (BrightWash Auto Detailing, Austin TX), services, prices and the
$25 deposit are **fictional demo data**. Replace `BUSINESS` in
`ai_agent.py` with a real merchant profile when reusing this for the
US small-business agent line.

## Notes

- Mock mode returns mock orders shaped like real Orders API v2 responses
  and always reuses id `MOCK-ORDER-001` — fine for a demo, not for
  production.
- The webhook endpoint logs events only. In production, verify the webhook
  signature with PayPal's verify-webhook-signature API before trusting it.
- Date/time parsing in the demo brain is intentionally simple (it keeps
  the raw phrase like "tomorrow 10:00 AM"); use a real date parser for
  a production agent.
