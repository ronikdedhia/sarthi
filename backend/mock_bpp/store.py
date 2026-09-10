"""In-memory order state for the mock BPP -- resets on process restart. A real ONDC BPP
is a separate network participant with its own persistence; this simulator only needs to
remember enough per-transaction state to make select -> init -> confirm coherent within
one dev/demo process. Not a data layer Sarthi itself should ever depend on directly."""

import threading

_lock = threading.Lock()
_orders = {}  # transaction_id -> dict


def remember_selection(transaction_id, provider_id, item_id):
    with _lock:
        _orders[transaction_id] = {"provider_id": provider_id, "item_id": item_id, "status": "selected"}


def mark_initiated(transaction_id):
    with _lock:
        _orders[transaction_id]["status"] = "initiated"


def confirm_order(transaction_id, order_id):
    with _lock:
        _orders[transaction_id]["status"] = "confirmed"
        _orders[transaction_id]["order_id"] = order_id


def get_order(transaction_id):
    with _lock:
        return _orders.get(transaction_id)
