"""Demo web app: AI customer-service assistant + PayPal sandbox checkout.

Run:
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # mock mode works with no keys
    python3 app.py         # -> http://localhost:5000

Modes (PAYPAL_MODE env):
    mock    - no network, no credentials; PayPal calls return mock data
              shaped like the real Orders API v2 responses.
    sandbox - real PayPal sandbox calls; requires PAYPAL_CLIENT_ID and
              PAYPAL_CLIENT_SECRET from the user's own PayPal Developer app.
"""

import os

from flask import Flask, jsonify, render_template, request

from ai_agent import AIAgent
from paypal_client import PayPalClient
from store import confirm_booking, create_booking, get_booking, list_bookings, record_order

app = Flask(__name__)
agent = AIAgent()
paypal = PayPalClient()

SESSIONS = {}


def get_session(session_id):
    return SESSIONS.setdefault(session_id, {"pending_booking": None, "booking_id": None})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    session_id = data.get("session_id", "demo-session")
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Please type a message."}), 400

    session = get_session(session_id)
    reply, action = agent.reply(message, session)

    payload = {"reply": reply}
    if action and action.get("type") == "booking_created":
        booking = create_booking(**action["booking"])
        session["booking_id"] = booking["id"]
        session["pending_booking"] = None
        payload["booking"] = booking
    elif action and action.get("type") == "create_deposit_order":
        booking = get_booking(session.get("booking_id") or "")
        if not booking:
            payload["reply"] = "I don't see a booking yet. Let's book first — which service would you like?"
            return jsonify(payload)
        order = paypal.create_order(
            amount=action["amount"],
            description=f"Deposit for {booking['service']} booking {booking['id']}",
        )
        record_order(order)
        booking["deposit_order_id"] = order["id"]
        payload["payment"] = {
            "order_id": order["id"],
            "amount": action["amount"],
            "approve_url": order.get("approve_url"),
            "mock": paypal.mode == "mock",
        }
    return jsonify(payload)


@app.route("/api/paypal/create-order", methods=["POST"])
def create_order_route():
    """Direct order creation (for testing the PayPal client without chat)."""
    data = request.get_json(force=True, silent=True) or {}
    order = paypal.create_order(
        amount=data.get("amount", 25),
        description=data.get("description", "Demo deposit"),
    )
    record_order(order)
    return jsonify(order)


@app.route("/api/paypal/return")
def paypal_return():
    """PayPal redirects here after the buyer approves. Capture + confirm."""
    order_id = request.args.get("token", "")
    result = paypal.capture_order(order_id)
    booking = next(
        (b for b in list_bookings() if b.get("deposit_order_id") == order_id),
        None,
    )
    if result.get("status") == "COMPLETED" and booking:
        confirm_booking(booking["id"])
        message = (
            f"Payment completed for order {order_id}. "
            f"Booking {booking['id']} ({booking['service']} at {booking['date_time']}) "
            f"is now confirmed."
        )
        return (
            f"<h1>Payment successful (demo)</h1><p>{message}</p>"
            f"<p><a href='/'>Back to chat</a></p>"
        )
    return (
        f"<h1>Payment not completed</h1>"
        f"<p>Order {order_id}: {result.get('status')}</p>"
        f"<p><a href='/'>Back to chat</a></p>",
        400,
    )


@app.route("/api/paypal/cancel")
def paypal_cancel():
    return "<h1>Payment cancelled</h1><p>No charge was made.</p><p><a href='/'>Back to chat</a></p>"


@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    """Receive PayPal webhook events. Logs only.

    TODO (production): verify the webhook signature with PayPal's
    /v1/notifications/verify-webhook-signature before trusting it.
    """
    event = request.get_json(force=True, silent=True) or {}
    app.logger.info("PayPal webhook received: %s", event.get("event_type"))
    return jsonify({"received": True})


@app.route("/api/bookings")
def bookings():
    return jsonify(list_bookings())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
