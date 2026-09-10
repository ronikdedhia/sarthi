"""Drives one TripLeg's booking through ONDC's real select -> init -> confirm sequence
(via ondc_adapter.client), advancing Booking's state machine (models.py) at each step.

Phase 1 scope: a single leg, booked synchronously end-to-end in one call — Phase 2's
"book multiple legs, handle one leg's price/availability changing mid-booking, replan"
(ARCHITECTURE.md) is out of scope here on purpose."""
from django.db import transaction as db_transaction

from ondc_adapter.client import OndcRequestError
from ondc_adapter import client

from .models import Booking, TripLeg


class BookingFailedError(Exception):
    """Wraps whichever step (select/init/confirm) actually failed, with the partial
    Booking left in its last successfully-reached state (STATUS_FAILED on top of that)
    rather than silently discarded — a partially-booked leg is exactly the kind of state
    a real trip needs to surface, not hide."""

    def __init__(self, step, booking, original_error):
        super().__init__(f"booking failed at {step}: {original_error}")
        self.step = step
        self.booking = booking
        self.original_error = original_error


def book_leg(trip, transaction_id, bpp_id, item_id, item_name, provider_name, fare, eta_minutes, raw_offer):
    """Creates the TripLeg + Booking rows, then drives select -> init -> confirm.
    Returns the (now STATUS_CONFIRMED) Booking. Raises BookingFailedError on any step's
    failure — the Booking is still saved (as STATUS_FAILED) so the failure is visible
    and inspectable, not just an exception that vanishes with the request."""
    with db_transaction.atomic():
        trip_leg = TripLeg.objects.create(
            trip=trip, bpp_id=bpp_id, provider_name=provider_name, item_id=item_id,
            fare=fare, eta_minutes=eta_minutes, raw_offer=raw_offer,
        )
        booking = Booking.objects.create(trip_leg=trip_leg, ondc_transaction_id=transaction_id)

    def _fail(step, error):
        booking.transition_to(Booking.STATUS_FAILED)
        raise BookingFailedError(step, booking, error)

    try:
        client.select(transaction_id, bpp_id, item_id)
    except OndcRequestError as e:
        _fail("select", e)
    booking.transition_to(Booking.STATUS_SELECTED)

    try:
        client.init(transaction_id)
    except OndcRequestError as e:
        _fail("init", e)
    booking.transition_to(Booking.STATUS_INITIATED)

    try:
        order_id, _ = client.confirm(transaction_id)
    except OndcRequestError as e:
        _fail("confirm", e)
    booking.ondc_order_id = order_id
    booking.save(update_fields=["ondc_order_id"])
    booking.transition_to(Booking.STATUS_CONFIRMED)

    return booking
