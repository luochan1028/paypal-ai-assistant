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

Robustness notes (this improvement pass):
  - Bad JSON bodies and PayPal API failures return friendly JSON errors
    (400/502), never an unhandled 500 page.
  - A confirmed booking cannot be charged a second deposit; a cancelled
    booking must be rebooked before paying.
  - The PayPal return page renders a full confirmation card, not bare text.
  - The webhook endpoint verifies the PayPal signature when configured
    and reports the verification outcome instead of silently trusting it.
"""

import os

from flask import Flask, jsonify, render_template, request

from ai_agent import AIAgent
from paypal_client import PayPalClient
from store import (cancel_booking, confirm_booking, create_booking,
                   get_booking, list_bookings, record_order,
                   set_deposit_order_id)

app = Flask(__name__)
agent = AIAgent()
paypal = PayPalClient()

SESSIONS = {}


def get_session(session_id):
    return SESSIONS.setdefault(session_id, {"pending_booking": None, "booking_id": None})


def _json_body():
    """Parsed JSON body, or None when the body is missing/invalid."""
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "mode": paypal.mode})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = _json_body()
    if data is None:
        return jsonify({"error": "Request body must be valid JSON."}), 400
    session_id = data.get("session_id", "demo-session")
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Please type a message."}), 400

    session = get_session(session_id)
    try:
        reply, action = agent.reply(message, session)
    except Exception:
        app.logger.exception("Agent failed on message %r", message)
        return jsonify({"reply": "Sorry — something went wrong on my side. Please try again."}), 500

    payload = {"reply": reply}
    if action and action.get("type") == "booking_created":
        booking = create_booking(**action["booking"])
        session["booking_id"] = booking["id"]
        session["pending_booking"] = None
        payload["booking"] = booking
    elif action and action.get("type") == "cancel_booking":
        booking = get_booking(session.get("booking_id") or "")
        if booking and booking["status"] != "confirmed":
            cancel_booking(booking["id"])
            booking = get_booking(booking["id"])
            session["booking_id"] = None
            payload["reply"] = (
                f"Done — booking {booking['id']} ({booking['service']} at "
                f"{booking['date_time']}) is cancelled. No deposit was charged."
            )
            payload["booking"] = booking
        else:
            payload["reply"] = "There's no active booking to cancel in this chat."
    elif action and action.get("type") == "create_deposit_order":
        booking = get_booking(session.get("booking_id") or "")
        if not booking:
            payload["reply"] = "I don't see a booking yet. Let's book first — which service would you like?"
            return jsonify(payload)
        if booking["status"] == "confirmed":
            payload["reply"] = (
                f"Booking {booking['id']} is already confirmed — no second deposit needed."
            )
            return jsonify(payload)
        if booking["status"] == "cancelled":
            payload["reply"] = (
                "That booking was cancelled. Let's make a new one — which service would you like?"
            )
            return jsonify(payload)
        try:
            order = paypal.create_order(
                amount=action["amount"],
                description=f"Deposit for {booking['service']} booking {booking['id']}",
            )
        except Exception:
            app.logger.exception("PayPal create_order raised")
            return jsonify({"error": "PayPal is unreachable right now. Please try again."}), 502
        if order.get("status") == "ERROR":
            return jsonify({"error": order.get("error", "PayPal order creation failed.")}), 502
        record_order(order)
        set_deposit_order_id(booking["id"], order["id"])
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
    data = _json_body() or {}
    try:
        order = paypal.create_order(
            amount=data.get("amount", 25),
            description=data.get("description", "Demo deposit"),
        )
    except Exception:
        app.logger.exception("PayPal create_order raised")
        return jsonify({"error": "PayPal is unreachable right now. Please try again."}), 502
    if order.get("status") == "ERROR":
        return jsonify({"error": order.get("error", "PayPal order creation failed.")}), 502
    record_order(order)
    return jsonify(order)


@app.route("/api/paypal/return")
def paypal_return():
    """PayPal redirects here after the buyer approves. Capture + confirm."""
    order_id = request.args.get("token", "")
    if not order_id:
        return (
            "<h1>Payment not completed</h1><p>No order token was returned.</p>"
            "<p><a href='/'>Back to chat</a></p>",
            400,
        )
    try:
        result = paypal.capture_order(order_id)
    except Exception:
        app.logger.exception("PayPal capture raised for %s", order_id)
        return (
            "<h1>Payment error</h1><p>PayPal is unreachable right now. Please try again.</p>"
            "<p><a href='/'>Back to chat</a></p>",
            502,
        )
    booking = next(
        (b for b in list_bookings() if b.get("deposit_order_id") == order_id),
        None,
    )
    if result.get("status") == "COMPLETED" and booking:
        confirm_booking(booking["id"])
        details = paypal.get_order_details(order_id)
        detail_line = ""
        if details.get("status") not in ("ERROR", "MOCK"):
            detail_line = f"<p>PayPal order status: {details['status']}.</p>"
        return (
            "<h1>Payment successful (demo)</h1>"
            "<div style='border:1px solid #ccc;border-radius:8px;padding:1rem;max-width:480px'>"
            f"<p><strong>Booking {booking['id']}</strong> — {booking['service']}</p>"
            f"<p>When: {booking['date_time']}</p>"
            f"<p>Name: {booking['customer_name']}</p>"
            f"<p>Deposit: $25 via PayPal order {order_id}</p>"
            f"<p>Status: <strong>confirmed</strong></p>"
            f"{detail_line}</div>"
            "<p><a href='/'>Back to chat</a></p>"
        )
    reason = result.get("error") or f"Order {order_id}: {result.get('status')}"
    return (
        "<h1>Payment not completed</h1>"
        f"<p>{reason}</p>"
        "<p><a href='/'>Back to chat</a></p>",
        400,
    )


@app.route("/api/paypal/cancel")
def paypal_cancel():
    return "<h1>Payment cancelled</h1><p>No charge was made.</p><p><a href='/'>Back to chat</a></p>"


@app.route("/api/paypal/webhook", methods=["POST"])
def paypal_webhook():
    """Receive PayPal webhook events and verify the signature when configured.

    Verification outcome is reported in the response; unverified events
    are logged, not silently trusted.
    """
    event = request.get_json(force=True, silent=True) or {}
    raw = request.get_data()
    verification = paypal.verify_webhook_signature(request.headers, event)
    app.logger.info(
        "PayPal webhook received: %s (verified=%s)",
        event.get("event_type"), verification.get("verified"),
    )
    return jsonify({"received": True, "webhook_verified": verification})


@app.route("/api/bookings")
def bookings():
    return jsonify(list_bookings())


@app.route("/api/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking_route(booking_id):
    booking = get_booking(booking_id)
    if not booking:
        return jsonify({"error": f"No booking {booking_id}."}), 404
    if booking["status"] == "confirmed":
        return jsonify({"error": "A confirmed booking cannot be cancelled from this demo."}), 409
    cancel_booking(booking_id)
    return jsonify(booking)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
