"""In-memory order state for the mock BPP -- resets on process restart. A real ONDC BPP
is a separate network participant with its own persistence; this simulator only needs to
remember enough per-transaction state to make select -> init -> confirm coherent within
one dev/demo process. Not a data layer Sarthi itself should ever depend on directly.

BUILD_PLAN.md Phase 3 (live tracking): a confirmed order no longer sits at "confirmed"
forever -- get_order computes its CURRENT status from elapsed real time since confirmation
(confirmed -> in_progress -> completed, via settings.MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS /
MOCK_ORDER_COMPLETED_AFTER_SECONDS), so a real poll loop (bookings.services.sync_booking_status)
has genuine state changes to observe over time, not a single static value.
"""

import threading
from datetime import datetime

from django.conf import settings

_lock = threading.Lock()
_orders = {}  # transaction_id -> dict


def remember_selection(transaction_id, domain, provider_id, item_id):
    with _lock:
        _orders[transaction_id] = {
            "domain": domain, "provider_id": provider_id, "item_id": item_id, "status": "selected",
        }


def mark_initiated(transaction_id):
    with _lock:
        _orders[transaction_id]["status"] = "initiated"


def confirm_order(transaction_id, order_id, now=None):
    """now is injectable for tests -- everything downstream of confirmation (elapsed-time
    status computation in get_order) is measured relative to this timestamp."""
    now = now or datetime.now()
    with _lock:
        _orders[transaction_id]["status"] = "confirmed"
        _orders[transaction_id]["order_id"] = order_id
        _orders[transaction_id]["confirmed_at"] = now


def _compute_current_status(order, now):
    """Pure: given a raw order dict and the current time, returns the status it should
    report right now. Only "confirmed" orders progress -- selected/initiated/cancelled/
    failed states are exactly what was last written, no time-based logic applies to them."""
    if order["status"] != "confirmed" or "confirmed_at" not in order:
        return order["status"]

    elapsed = (now - order["confirmed_at"]).total_seconds()
    in_progress_after = settings.MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS
    completed_after = in_progress_after + settings.MOCK_ORDER_COMPLETED_AFTER_SECONDS

    if elapsed >= completed_after:
        return "completed"
    if elapsed >= in_progress_after:
        return "in_progress"
    return "confirmed"


def get_order(transaction_id, now=None):
    """Returns a COPY of the order dict with `status` computed for the current elapsed
    time since confirmation, not the raw write-once value confirm_order stored -- this is
    what makes a status poll actually show real progression instead of a static value
    forever. Returns None for an unknown transaction, same as before this existed."""
    now = now or datetime.now()
    with _lock:
        order = _orders.get(transaction_id)
        if order is None:
            return None
        order = dict(order)

    order["status"] = _compute_current_status(order, now)
    return order
