"""AI conversation layer for the demo shop assistant.

Two layers:
  1. `AIAgent` — rule-based demo brain. It understands a small set of
     intents (hours, prices, booking, deposit payment) and keeps a tiny
     multi-turn booking state. No API key needed; this is what the demo
     runs on out of the box.
  2. `LLMClient` — pluggable model call. If AI_PROVIDER is set to an
     OpenAI-compatible provider and AI_API_KEY is present, `complete()`
     calls the model; otherwise it returns None and the rule-based brain
     answers. Swap this class to plug in any other model.

The rule-based brain is intentionally small: it demonstrates the tool-call
pattern (booking tool, payment tool) that the real agent will keep.
"""

import os
import re

import requests

# Fictional demo business. Replace with a real merchant profile when
# reusing this for the US small-business agent line.
BUSINESS = {
    "name": "BrightWash Auto Detailing",
    "city": "Austin, TX",
    "hours": "Monday–Saturday, 9:00 AM – 6:00 PM",
    "services": {
        "basic wash": 29,
        "full detail": 129,
        "ceramic coating": 299,
    },
    "deposit": 25,
}

TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.IGNORECASE)
GREETING_RE = re.compile(r"\b(hi|hello|hey)\b", re.IGNORECASE)


class LLMClient:
    """Optional LLM call. Returns None when not configured."""

    def __init__(self):
        self.provider = os.environ.get("AI_PROVIDER", "demo")
        self.api_key = os.environ.get("AI_API_KEY", "")
        self.base_url = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.environ.get("AI_MODEL", "")

    def complete(self, messages):
        if self.provider == "demo" or not self.api_key or not self.model:
            return None
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class AIAgent:
    def __init__(self, llm=None):
        self.llm = llm or LLMClient()

    # -- intent helpers -------------------------------------------------
    def _find_service(self, text):
        low = text.lower()
        for name in BUSINESS["services"]:
            if name in low:
                return name
        return None

    def _find_time(self, text):
        """Demo-grade time parsing: keeps the raw phrase (e.g. 'tomorrow 10:00 AM')."""
        match = TIME_RE.search(text)
        if not match:
            return None
        hour, minute, meridiem = match.group(1), match.group(2) or "00", match.group(3).upper()
        low = text.lower()
        day = "tomorrow" if "tomorrow" in low else ("today" if "today" in low else "")
        label = f"{hour}:{minute} {meridiem}"
        return f"{day} {label}".strip() if day else label

    def _price_list(self):
        return ", ".join(f"{name} (${price})" for name, price in BUSINESS["services"].items())

    # -- main entry ------------------------------------------------------
    def reply(self, user_text, session):
        """Return (reply_text, action). Action may be None or a tool-call dict."""
        low = user_text.lower()
        pending = session.get("pending_booking") or {}

        # Step 3 of booking: we asked for a name.
        if pending.get("awaiting") == "name":
            booking = {
                "customer_name": user_text.strip(),
                "service": pending["service"],
                "date_time": pending["date_time"],
            }
            return (
                f"Thanks, {booking['customer_name']}! Your {pending['service']} is booked for "
                f"{pending['date_time']}. A ${BUSINESS['deposit']} deposit confirms it — "
                f"just say 'pay deposit' and I'll send you the PayPal link.",
                {"type": "booking_created", "booking": booking},
            )

        # Step 2 of booking: we asked for a time.
        if pending.get("awaiting") == "time":
            when = self._find_time(user_text)
            if not when:
                return ("What time works for you? For example: 'tomorrow 10am'.", None)
            pending["date_time"] = when
            pending["awaiting"] = "name"
            return (
                f"Got it — {pending['service']} at {when}. May I have your name for the booking?",
                None,
            )

        # Payment intent.
        if any(word in low for word in ["pay", "deposit", "checkout"]):
            if session.get("booking_id"):
                return (
                    f"Here's your ${BUSINESS['deposit']} deposit link. After you approve it "
                    f"on PayPal, I'll confirm the booking automatically.",
                    {"type": "create_deposit_order", "amount": BUSINESS["deposit"]},
                )
            return ("You don't have a booking yet. Which service would you like to book?", None)

        # Booking intent.
        if any(word in low for word in ["book", "appointment", "reserve"]):
            service = self._find_service(user_text)
            if not service:
                return (f"Sure! Which service? We offer: {self._price_list()}.", None)
            when = self._find_time(user_text)
            if not when:
                session["pending_booking"] = {"service": service, "awaiting": "time"}
                return (
                    f"Great choice — {service} (${BUSINESS['services'][service]}). "
                    f"What time works for you?",
                    None,
                )
            session["pending_booking"] = {"service": service, "date_time": when, "awaiting": "name"}
            return (f"{service} at {when} — noted. May I have your name for the booking?", None)

        # Hours / prices.
        if any(word in low for word in ["hour", "open", "close"]):
            return (f"We're open {BUSINESS['hours']}.", None)
        if any(word in low for word in ["price", "cost", "how much", "menu", "service"]):
            return (
                f"Our services: {self._price_list()}. "
                f"A ${BUSINESS['deposit']} deposit confirms any booking.",
                None,
            )
        if GREETING_RE.search(user_text):
            return (
                f"Hi! I'm the assistant for {BUSINESS['name']} in {BUSINESS['city']}. "
                f"I can share hours and prices, book an appointment, and take your deposit via PayPal. "
                f"What can I do for you?",
                None,
            )

        # Optional LLM fallback, then a guided fallback.
        llm_text = self.llm.complete(
            [
                {
                    "role": "system",
                    "content": f"You are a helpful assistant for {BUSINESS['name']}. Keep replies short.",
                },
                {"role": "user", "content": user_text},
            ]
        )
        if llm_text:
            return (llm_text, None)
        return (
            "I can help with hours, prices, booking an appointment, or paying your deposit. "
            "Try: 'Book a full detail tomorrow 10am'.",
            None,
        )
