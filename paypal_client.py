"""PayPal Orders API v2 client with a mock mode.

Mock mode (PAYPAL_MODE=mock, the default) returns responses shaped like
the real API so the demo runs with no credentials and no network.
Sandbox mode (PAYPAL_MODE=sandbox) makes real sandbox calls and needs
PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from the user's own PayPal
Developer app (never commit them — use .env).
"""

import os

import requests

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


class PayPalClient:
    def __init__(self, mode=None, client_id=None, client_secret=None, base_url=None):
        self.mode = (mode or os.environ.get("PAYPAL_MODE", "mock")).lower()
        self.client_id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self.base_url = base_url or os.environ.get("PAYPAL_BASE_URL", "http://localhost:5000")
        self._token = None

    # -- auth ------------------------------------------------------------
    def _get_token(self):
        if self._token:
            return self._token
        resp = requests.post(
            f"{SANDBOX_BASE}/v1/oauth2/token",
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    # -- orders ------------------------------------------------------------
    def create_order(self, amount, currency="USD", description=""):
        """Create an order. Returns {id, status, approve_url}."""
        if self.mode == "mock":
            return {
                "id": "MOCK-ORDER-001",
                "status": "CREATED",
                "approve_url": "https://www.sandbox.paypal.com/checkoutnow?token=MOCK-ORDER-001",
                "mock": True,
            }
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
        data = resp.json()
        approve_url = next(
            (link["href"] for link in data.get("links", []) if link.get("rel") == "approve"),
            "",
        )
        return {"id": data["id"], "status": data["status"], "approve_url": approve_url}

    def capture_order(self, order_id):
        """Capture an approved order. Returns {id, status}."""
        if self.mode == "mock":
            return {"id": order_id, "status": "COMPLETED", "mock": True}
        token = self._get_token()
        resp = requests.post(
            f"{SANDBOX_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 201:
            return {"id": order_id, "status": "FAILED", "error": resp.text[:500]}
        return {"id": order_id, "status": resp.json().get("status", "COMPLETED")}
