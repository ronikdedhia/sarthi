"""Drives one TripLeg's booking through ONDC's real select -> init -> confirm sequence
(via ondc_adapter.client), advancing Booking's state machine (models.py) at each step.

Phase 1 scope was a single leg, booked synchronously end-to-end in one call. Phase 2
adds book_itinerary: book several legs (each possibly a different ONDC domain) in
order, stopping and surfacing clearly at whichever leg first fails -- see
ItineraryBookingResult and book_itinerary's docstring for why this surfaces rather than
auto-replans."""
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


def book_leg(trip, transaction_id, bpp_id, item_id, item_name, provider_name, fare, eta_minutes, raw_offer,
             domain=TripLeg.DOMAIN_RIDE_HAILING, mode="", sequence=0):
    """Creates the TripLeg + Booking rows, then drives select -> init -> confirm.
    Returns the (now STATUS_CONFIRMED) Booking. Raises BookingFailedError on any step's
    failure — the Booking is still saved (as STATUS_FAILED) so the failure is visible
    and inspectable, not just an exception that vanishes with the request.

    domain/mode/sequence default to Phase 1's original values (TRV10, no label, leg 0),
    so every existing call site (single-leg book_leg calls with no domain/mode/sequence
    passed) behaves exactly as before."""
    with db_transaction.atomic():
        trip_leg = TripLeg.objects.create(
            trip=trip, domain=domain, mode=mode, sequence=sequence, bpp_id=bpp_id,
            provider_name=provider_name, item_id=item_id, fare=fare, eta_minutes=eta_minutes,
            raw_offer=raw_offer,
        )
        booking = Booking.objects.create(trip_leg=trip_leg, ondc_transaction_id=transaction_id)

    def _fail(step, error):
        booking.transition_to(Booking.STATUS_FAILED)
        raise BookingFailedError(step, booking, error)

    try:
        client.select(transaction_id, bpp_id, item_id, domain=domain)
    except OndcRequestError as e:
        _fail("select", e)
    booking.transition_to(Booking.STATUS_SELECTED)

    try:
        client.init(transaction_id, domain=domain)
    except OndcRequestError as e:
        _fail("init", e)
    booking.transition_to(Booking.STATUS_INITIATED)

    try:
        order_id, _ = client.confirm(transaction_id, domain=domain)
    except OndcRequestError as e:
        _fail("confirm", e)
    booking.ondc_order_id = order_id
    booking.save(update_fields=["ondc_order_id"])
    booking.transition_to(Booking.STATUS_CONFIRMED)

    return booking


class ItineraryBookingResult:
    """Outcome of booking a whole multi-leg itinerary. `bookings` holds every leg
    successfully confirmed so far, in order; if a leg failed, `failed_leg_index` +
    `failure` say exactly which one and why, and `legs_not_attempted` says how many
    legs after it were never even tried."""

    def __init__(self, trip, bookings, failed_leg_index=None, failure=None, legs_not_attempted=0):
        self.trip = trip
        self.bookings = bookings
        self.failed_leg_index = failed_leg_index
        self.failure = failure
        self.legs_not_attempted = legs_not_attempted

    @property
    def fully_booked(self):
        return self.failed_leg_index is None


def book_itinerary(trip, leg_specs):
    """Books each leg in leg_specs (a list of dicts shaped like the /api/trips/plan/
    response's per-leg objects: transaction_id/domain/bpp_id/item_id/item_name/
    provider_name/fare/eta_minutes/mode/raw) IN ORDER, via book_leg.

    ARCHITECTURE.md's Phase 2 scope: "leg 2 confirms but leg 3's price/availability
    changed by the time you get to it — replan, don't just crash." This stops at the
    first failing leg and returns a result that clearly shows what's already confirmed,
    what failed and why, and what was never attempted — rather than leaving a
    half-booked trip's state ambiguous, or (worse) silently continuing to book legs
    after one has already failed. Automatic re-planning around a failed leg is a real
    Phase 3+ feature (it needs a fresh call back into trip_planner.services with the
    remaining origin/destination), not bundled into this booking-orchestration function.
    """
    bookings = []
    for index, spec in enumerate(leg_specs):
        try:
            booking = book_leg(
                trip, spec["transaction_id"], spec["bpp_id"], spec["item_id"], spec["item_name"],
                spec["provider_name"], spec["fare"], spec["eta_minutes"], spec.get("raw", {}),
                domain=spec.get("domain", TripLeg.DOMAIN_RIDE_HAILING), mode=spec.get("mode", ""),
                sequence=index,
            )
        except BookingFailedError as e:
            return ItineraryBookingResult(
                trip=trip, bookings=bookings, failed_leg_index=index, failure=e,
                legs_not_attempted=len(leg_specs) - index - 1,
            )
        bookings.append(booking)

    return ItineraryBookingResult(trip=trip, bookings=bookings)
