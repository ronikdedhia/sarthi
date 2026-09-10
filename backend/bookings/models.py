"""Trip/booking persistence + the booking state machine (ARCHITECTURE.md's `bookings` app).

Phase 1 scope was a Trip with exactly one TripLeg (single-mode, single-leg booking).
Phase 2 (BUILD_PLAN.md) needed no schema change for a Trip to hold multiple TripLegs --
TripLeg.trip was already a plain ForeignKey (Trip.legs), not OneToOne -- so a multi-leg
itinerary is just several TripLeg rows sharing one Trip, booked in order by
bookings.services.book_itinerary.
"""
import uuid

from django.db import models


class Trip(models.Model):
    """One trip request from a user — Phase 1: always exactly one leg."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    requested_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip({self.origin} -> {self.destination})"


class TripLeg(models.Model):
    """One leg of a trip. Phase 1 only ever created TRV10 (ride-hailing) legs; Phase 2
    adds TRV11 (metro/intracity bus) and TRV12 (intercity bus/flight) as real choices,
    plus `mode` (a free-text label like "metro"/"flight"/"cab" from ondc_adapter's Offer,
    for display -- not used for any routing logic, that's trip_planner.planner's job)."""

    DOMAIN_RIDE_HAILING = "ONDC:TRV10"
    DOMAIN_METRO_BUS = "ONDC:TRV11"
    DOMAIN_INTERCITY = "ONDC:TRV12"
    DOMAIN_CHOICES = [
        (DOMAIN_RIDE_HAILING, "Ride hailing"),
        (DOMAIN_METRO_BUS, "Metro / intracity bus"),
        (DOMAIN_INTERCITY, "Intercity bus / flight"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="legs")
    domain = models.CharField(max_length=32, choices=DOMAIN_CHOICES, default=DOMAIN_RIDE_HAILING)
    # Order within the trip -- Phase 1 never needed this (always exactly one leg); Phase 2
    # itineraries are booked leg-by-leg in this order (bookings.services.book_itinerary).
    sequence = models.PositiveIntegerField(default=0)
    mode = models.CharField(max_length=32, blank=True, default="")
    bpp_id = models.CharField(max_length=255)
    provider_name = models.CharField(max_length=255)
    item_id = models.CharField(max_length=255)  # the ONDC catalog item this leg books
    fare = models.DecimalField(max_digits=10, decimal_places=2)
    eta_minutes = models.PositiveIntegerField()
    # raw ONDC search-result payload for this offer, for debugging/replay —
    # ARCHITECTURE.md: "store raw ONDC request/response payloads for debugging"
    raw_offer = models.JSONField()

    class Meta:
        ordering = ["sequence"]

    def __str__(self):
        return f"{self.provider_name} ({self.domain}) — {self.fare}"


class Booking(models.Model):
    """The state machine for one TripLeg's booking — ARCHITECTURE.md's
    searched -> selected -> initiated -> confirmed -> in_progress -> completed/cancelled."""

    STATUS_SEARCHED = "searched"
    STATUS_SELECTED = "selected"
    STATUS_INITIATED = "initiated"
    STATUS_CONFIRMED = "confirmed"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_SEARCHED, "Searched"),
        (STATUS_SELECTED, "Selected"),
        (STATUS_INITIATED, "Initiated"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    ]

    # Legal forward transitions — anything not listed here is refused by transition_to().
    ALLOWED_TRANSITIONS = {
        STATUS_SEARCHED: {STATUS_SELECTED, STATUS_FAILED},
        STATUS_SELECTED: {STATUS_INITIATED, STATUS_FAILED},
        STATUS_INITIATED: {STATUS_CONFIRMED, STATUS_FAILED},
        STATUS_CONFIRMED: {STATUS_IN_PROGRESS, STATUS_CANCELLED},
        STATUS_IN_PROGRESS: {STATUS_COMPLETED, STATUS_CANCELLED},
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
        STATUS_FAILED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip_leg = models.OneToOneField(TripLeg, on_delete=models.CASCADE, related_name="booking")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SEARCHED)
    # ONDC's own correlation ids, needed to match async on_select/on_init/on_confirm
    # callbacks back to this booking (ARCHITECTURE.md: "Idempotency ... on
    # transaction_id/message_id").
    ondc_transaction_id = models.CharField(max_length=64)
    ondc_order_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class InvalidTransition(Exception):
        pass

    def transition_to(self, new_status):
        """Raises InvalidTransition rather than silently allowing an out-of-order
        state change — a confirmed leg quietly reverting to 'searched' because of a
        duplicated/out-of-order ONDC callback is exactly the kind of bug that's
        invisible until it corrupts a real booking."""
        allowed = self.ALLOWED_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise Booking.InvalidTransition(
                f"cannot transition booking {self.id} from {self.status!r} to {new_status!r} "
                f"(allowed: {sorted(allowed) or 'none — terminal state'})"
            )
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])

    def __str__(self):
        return f"Booking({self.trip_leg_id}, {self.status})"


class TrackingEvent(models.Model):
    """Append-only log of every ONDC callback received for a booking — ARCHITECTURE.md:
    "you'll want this for debugging async ONDC flows more than for the product itself."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="tracking_events")
    event_type = models.CharField(max_length=32)  # e.g. "on_select", "on_confirm", "on_status"
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at"]

    def __str__(self):
        return f"TrackingEvent({self.event_type} @ {self.received_at})"
