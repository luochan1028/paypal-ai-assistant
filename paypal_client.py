"""PayPal Orders API v2 client with a mock mode.

Mock mode (PAYPAL_MODE=mock, the default) returns responses shaped like
the real API so the demo runs with no credentials and no network.
Sandbox mode (PAYPAL_MODE=sandbox) makes real sandbox calls and needs
PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from the user's own PayPal
Developer app (never commit them — use .env).

Robustness notes (this improvement pass):
  - Every sandbox call is wrapped: network/API failures return a
    structured {"status": "ERROR", "error": ...} dict instead of raising,
    so the web layer can answer with a friendly message, never a 500.
  - Mock order ids are sequential (MOCK-ORDER-001, -002, ...), so a
    second booking no longer reuses the first booking's order id.
  - The OAuth token is cached with its expiry (expires_in) and refreshed
    when stale, instead of being kept forever.
  - Webhook signature verification is implemented (sandbox) and
    simulated (mock); see verify_webhook_signature().
"""

import itertools
import os
import time

import requests

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"

_mock_counter = itertools.count(1)


class PayPalClient:
    def __init__(self, mode=None, client_id=None, client_secret=None, base_url=None,
                 webhook_id=None):
        self.mode = (mode or os.environ.get("PAYPAL_MODE", "mock")).lower()
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self.base_url = base_url or os.environ.get("PAYPAL_BASE_URL", "http://localhost:5000")
        self.webhook_id = webhook_id or os.environ.get("PAYPAL_WEBHOOK_ID", "")
        self._token = None
        self._token_expires_at = 0

    # -- auth ------------------------------------------------------------
    def _get_token(self):
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            f"{SANDBOX_BASE}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Sandbox tokens live ~9h; keep a safety margin.
        self._token_expires_at = time.time() + int(data.get("expires_in", 32400))
        return self._token

    # -- orders ------------------------------------------------------------
    def create_order(self, amount, currency="USD", description=""):
        """Create an order. Returns {id, status, approve_url} or an ERROR dict."""
        if self.mode == "mock":
            order_id = f"MOCK-ORDER-{next(_mock_counter):03d}"
            return {
                "id": order_id,
                "status": "CREATED",
                "approve_url": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                "mock": True,
            }
        try:
            token = self._get_token()
            resp = requests.post(
                f"{SANDBOX_BASE}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "description": description,
                            "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                        }
                    ],
                    "application_context": {
                        "return_url": f"{self.base_url}/api/paypal/return",
                        "cancel_url": f"{self.base_url}/api/paypal/cancel",
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return {"id": "", "status": "ERROR", "error": f"PayPal create order failed: {exc}"}
        data = resp.json()
        approve_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"),
            "",
        )
        return {"id": data["id"], "status": data["status"], "approve_url": approve_url}

    def capture_order(self, order_id):
        """Capture an approved order. Returns {id, status} or an ERROR dict."""
        if self.mode == "mock":
            return {"id": order_id, "status": "COMPLETED", "mock": True}
        try:
            token = self._get_token()
            resp = requests.post(
                f"{SANDBOX_BASE}/v2/checkout/orders/{order_id}/capture",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code != 201:
                return {"id": order_id, "status": "FAILED", "error": resp.text[:500]}
        except requests.RequestException as exc:
            return {"id": order_id, "status": "ERROR", "error": f"PayPal capture failed: {exc}"}
        return {"id": order_id, "status": resp.json().get("status", "COMPLETED")}

    def get_order_details(self, order_id):
        """Read an order back (GET). Best-effort; returns an ERROR dict on failure."""
        if self.mode == "mock":
            return {"id": order_id, "status": "MOCK", "mock": True,
                    "note": "Mock mode has no stored order state to read back."}
        try:
            token = self._get_token()
            resp = requests.get(
                f"{SANDBOX_BASE}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return {"id": order_id, "status": "ERROR", "error": f"PayPal order lookup failed: {exc}"}
        data = resp.json()
        return {"id": data.get("id", order_id), "status": data.get("status", "UNKNOWN"),
                "intent": data.get("intent", ""), "raw": data}

    # -- webhooks ------------------------------------------------------------
    def verify_webhook_signature(self, headers, body):
        """Verify a PayPal webhook event.

        Sandbox mode calls PayPal's verify-webhook-signature API when
        PAYPAL_WEBHOOK_ID is configured; otherwise it reports that
        verification is not configured (never silently claims success).
        Mock mode simulates a successful verification.
        """
        if self.mode == "mock":
            return {"verified": True, "mock": True}
        if not self.webhook_id:
            return {"verified": False, "reason": "PAYPAL_WEBHOOK_ID is not configured"}
        try:
            token = self._get_token()
            resp = requests.post(
                f"{SANDBOX_BASE}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "auth_algo": headers.get("Paypal-Auth-Algo", ""),
                    "cert_url": headers.get("Paypal-Cert-Url", ""),
                    "transmission_id": headers.get("Paypal-Transmission-Id", ""),
                    "transmission_sig": headers.get("Paypal-Transmission-Sig", ""),
                    "transmission_time": headers.get("Paypal-Transmission-Time", ""),
                    "webhook_id": self.webhook_id,
                    "webhook_event": body,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            return {"verified": False, "error": f"Verification call failed: {exc}"}
        return {"verified": resp.json().get("verification_status") == "SUCCESS"}
