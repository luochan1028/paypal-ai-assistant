# Prototype: AI Shop Assistant + PayPal Sandbox Checkout

Demo for the PayPal AI Hackathon 2026. A chat assistant for a fictional
local service business: it answers hours/prices, books appointments, and
collects a deposit through PayPal — then confirms the booking automatically.
The agent closes the loop itself: booking stays `pending_deposit` until
money moves, and the PayPal callback flips it to `confirmed` with no human
in the loop. That deposit-as-commitment step is the product idea, not an
afterthought — it is what turns a soft hold into a booking that shows up.

## Judge quickstart (under 2 minutes, no keys)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # mock mode works with no keys filled in
python3 app.py              # -> http://localhost:5000
```

In the chat UI (or use the quick-reply chips):

1. "What are your hours?" / "How much is a full detail?"
2. "Book a full detail tomorrow 10am" → give your name when asked
3. "Pay deposit" → click the payment link
4. In mock mode, click **Simulate buyer approval** (the mock PayPal link
   is not a real order) → booking status flips to `confirmed`
5. Watch the **My bookings** panel: the same booking moves from
   `pending_deposit` to `confirmed`. Try **Cancel booking** on a pending
   one — it cancels, and a confirmed one refuses (409).

Check state anytime: `GET /api/bookings`, `GET /api/health`.

## Switch to the real PayPal sandbox

1. Create a sandbox app in your own PayPal Developer account and copy the
   Client ID / Secret into `.env` (never commit `.env` — it is gitignored).
2. Set `PAYPAL_MODE=sandbox` in `.env` and restart.
3. Approve the order with a PayPal sandbox buyer account; PayPal will
   redirect back to `/api/paypal/return`, which captures the order and
   confirms the booking.
4. Optional: set `PAYPAL_WEBHOOK_ID` so `/api/paypal/webhook` verifies the
   PayPal signature instead of only logging the event.

## How it is built (agentic loop)

```
customer message
  -> perceive intent (booking / payment / cancel / hours / price / help)
  -> plan missing slots (service -> time -> name) across turns
  -> act through tools: booking tool, PayPal order tool
  -> confirm via PayPal return redirect + capture (+ webhook verification)
```

| File | Role |
|---|---|
| `app.py` | Flask routes: chat, PayPal create/capture/return/webhook, bookings, health |
| `ai_agent.py` | Conversation layer: agentic loop (demo brain) + pluggable `LLMClient` |
| `paypal_client.py` | PayPal Orders API v2: create / capture / read-back / webhook verify (mock + sandbox) |
| `store.py` | In-memory bookings/orders (demo only; use a DB for a real product) |
| `templates/index.html` | Chat demo UI + shop card + live bookings panel |

## Tools used (for the Devpost "Tools" field)

- **PayPal Orders API v2 (sandbox)** — create order → buyer approval →
  capture → return redirect → order read-back; webhook signature
  verification. Mock mode returns identically shaped responses offline.
- **AI: agentic loop + pluggable model interface.** The default demo
  brain is rule-based intent + multi-turn slot filling (no key needed).
  `LLMClient` accepts any OpenAI-compatible provider/key/model via
  `.env`; when configured, it answers open-ended messages, and the
  tool-call loop is unchanged. No hosted model call is required to run
  the demo, and none is claimed.
- **Flask + requests** (Python standard stack, see `requirements.txt`).

## Demo data

The shop (BrightWash Auto Detailing, Austin TX), services, prices and the
$25 deposit are **fictional demo data**. Replace `BUSINESS` in
`ai_agent.py` with a real merchant profile when reusing this for the
US small-business agent line.

## Notes and honest limits

- Mock order ids are sequential (`MOCK-ORDER-001`, `-002`, …) so two
  bookings never share an order id; mock orders are not real PayPal
  orders and the UI labels them as mock.
- The webhook endpoint verifies the signature when `PAYPAL_WEBHOOK_ID`
  is set; without it, verification is reported as not configured, never
  silently claimed.
- Date/time parsing resolves "tomorrow"/"today" to real calendar dates;
  a bare time with no day word keeps just the time.
- Sandbox calls are wrapped: a PayPal outage returns a friendly JSON
  error (502), never an unhandled 500 page.
- In-memory store: bookings reset when the server restarts — fine for a
  demo, not for production.
- Real sandbox end-to-end (OAuth, create, capture) is implemented but
  not yet run against live sandbox: that step needs the user's own
  PayPal Developer keys and is listed as a user step, not claimed here.
