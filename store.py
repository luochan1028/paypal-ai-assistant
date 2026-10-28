"""In-memory store for demo bookings and orders.

Deliberately simple: the hackathon prototype does not need a database.
Replace with SQLite/Postgres when turning this into a product.
"""

import itertools
import time

_bookings = {}
_orders = {}
_counter = itertools.count(1)


def create_booking(customer_name, service, date_time, deposit_order_id=None):
    booking_id = f"BKG-{next(_counter):04d}"
    booking = {
        "id": booking_id,
        "customer_name": customer_name,
        "service": service,
        "date_time": date_time,
        "deposit_order_id": deposit_order_id,
        "status": "pending_deposit",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _bookings[booking_id] = booking
    return booking


def get_booking(booking_id):
    return _bookings.get(booking_id)


def confirm_booking(booking_id):
    booking = _bookings.get(booking_id)
    if booking:
        booking["status"] = "confirmed"
    return booking


def record_order(order):
    _orders[order["id"]] = order
    return order


def get_order(order_id):
    return _orders.get(order_id)


def list_bookings():
    return list(_bookings.values())
