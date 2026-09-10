import time

from django.test import LiveServerTestCase, override_settings

from bookings.models import Booking, Trip, TripLeg
from bookings.services import book_itinerary, book_leg, sync_booking_status, sync_trip_tracking
from ondc_adapter import client


class BookLegIntegrationTests(LiveServerTestCase):
    """Full stack: search against the real mock_bpp -> book_leg drives real
    select/init/confirm calls -> Booking ends up STATUS_CONFIRMED with a real order id."""

    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

    def test_booking_a_searched_offer_reaches_confirmed(self):
        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")

        with self._gateway_url_override():
            offers, transaction_id = client.search(trip.origin, trip.destination)
            offer = offers[0]

            booking = book_leg(
                trip, transaction_id, offer.bpp_id, offer.item_id, offer.item_name,
                offer.provider_name, offer.fare, offer.eta_minutes, offer.raw,
            )

        assert booking.status == Booking.STATUS_CONFIRMED
        assert booking.ondc_order_id.startswith("order-")
        assert Booking.objects.get(pk=booking.pk).status == Booking.STATUS_CONFIRMED


def _leg_spec(offer):
    """The shape book_itinerary/its API endpoint expect per leg -- matches exactly what
    /api/trips/plan/'s response already returns per leg (see trip_planner/views.py)."""
    return {
        "transaction_id": offer.transaction_id, "domain": offer.domain, "bpp_id": offer.bpp_id,
        "item_id": offer.item_id, "item_name": offer.item_name, "provider_name": offer.provider_name,
        "fare": offer.fare, "eta_minutes": offer.eta_minutes, "mode": offer.mode, "raw": offer.raw,
    }


class BookItineraryIntegrationTests(LiveServerTestCase):
    """BUILD_PLAN.md Phase 2: book_itinerary drives several real legs (each its own
    domain/transaction_id) in order -- the multi-leg counterpart to book_leg above."""

    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

    def test_every_leg_confirms_when_all_are_bookable(self):
        trip = Trip.objects.create(origin="Koramangala", destination="T Nagar")

        with self._gateway_url_override():
            offers = client.search_all_domains(trip.origin, trip.destination)
            auto_leg = next(o for o in offers if o.domain == "ONDC:TRV10" and o.item_id == "auto-standard")
            metro_leg = next(o for o in offers if o.domain == "ONDC:TRV11" and o.bpp_id == "namma-metro")

            result = book_itinerary(trip, [_leg_spec(auto_leg), _leg_spec(metro_leg)])

        assert result.fully_booked is True
        assert result.failed_leg_index is None
        assert len(result.bookings) == 2
        assert all(b.status == Booking.STATUS_CONFIRMED for b in result.bookings)

        legs = list(TripLeg.objects.filter(trip=trip).order_by("sequence"))
        assert [leg.domain for leg in legs] == ["ONDC:TRV10", "ONDC:TRV11"]
        assert [leg.sequence for leg in legs] == [0, 1]

    def test_a_failing_leg_stops_booking_and_reports_clearly_rather_than_silently_continuing(self):
        """ARCHITECTURE.md Phase 2: "leg 2 confirms but leg 3's price/availability
        changed by the time you get to it — replan, don't just crash." This proves the
        "surface clearly" half: leg 0 confirms for real, leg 1 (a bogus/expired offer)
        fails, and the result says exactly that rather than raising or half-booking
        silently."""
        trip = Trip.objects.create(origin="Koramangala", destination="T Nagar")

        with self._gateway_url_override():
            offers = client.search_all_domains(trip.origin, trip.destination)
            good_leg = next(o for o in offers if o.domain == "ONDC:TRV10" and o.item_id == "auto-standard")
            # a leg whose item_id no longer exists in the mock BPP's catalog by the time
            # we try to book it -- the real-world equivalent of "price/availability
            # changed mid-booking" this ARCHITECTURE.md scenario describes.
            stale_leg_spec = _leg_spec(good_leg)
            stale_leg_spec.update(item_id="no-such-item-anymore", bpp_id=good_leg.bpp_id)

            result = book_itinerary(trip, [_leg_spec(good_leg), stale_leg_spec])

        assert result.fully_booked is False
        assert len(result.bookings) == 1
        assert result.bookings[0].status == Booking.STATUS_CONFIRMED
        assert result.failed_leg_index == 1
        assert result.failure.step == "select"
        assert result.legs_not_attempted == 0  # it was the last leg in this itinerary

        # the failed leg's own Booking is still persisted, as STATUS_FAILED -- visible
        # and inspectable, not discarded (same contract book_leg already guarantees).
        assert result.failure.booking.status == Booking.STATUS_FAILED
        assert Booking.objects.filter(trip_leg__trip=trip).count() == 2


@override_settings(MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS=1, MOCK_ORDER_COMPLETED_AFTER_SECONDS=1)
class SyncBookingStatusIntegrationTests(LiveServerTestCase):
    """BUILD_PLAN.md Phase 3: sync_booking_status/sync_trip_tracking actually advance
    Sarthi's own Booking rows over REAL elapsed time and REAL polls through the full HTTP
    stack -- not a mocked single-state check. Thresholds shrunk to 1s+1s via
    override_settings so this doesn't need to wait out the real (demo-friendly but still
    several-second) defaults."""

    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

    def _book_one_leg(self, trip):
        with self._gateway_url_override():
            offers, transaction_id = client.search(trip.origin, trip.destination)
            offer = offers[0]
            return book_leg(
                trip, transaction_id, offer.bpp_id, offer.item_id, offer.item_name,
                offer.provider_name, offer.fare, offer.eta_minutes, offer.raw,
            )

    def test_a_confirmed_booking_advances_to_in_progress_then_completed_over_real_time(self):
        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")
        booking = self._book_one_leg(trip)
        assert booking.status == Booking.STATUS_CONFIRMED

        with self._gateway_url_override():
            unchanged = sync_booking_status(booking)
            assert unchanged.status == Booking.STATUS_CONFIRMED  # too soon to have advanced

            time.sleep(1.2)
            advanced = sync_booking_status(booking)
            assert advanced.status == Booking.STATUS_IN_PROGRESS

            time.sleep(1.2)
            completed = sync_booking_status(booking)
            assert completed.status == Booking.STATUS_COMPLETED

        # persisted, not just returned in-memory
        assert Booking.objects.get(pk=booking.pk).status == Booking.STATUS_COMPLETED

    def test_a_real_transition_records_a_tracking_event(self):
        from bookings.models import TrackingEvent

        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")
        booking = self._book_one_leg(trip)

        with self._gateway_url_override():
            time.sleep(1.2)
            sync_booking_status(booking)

        events = TrackingEvent.objects.filter(booking=booking, event_type="on_status")
        assert events.count() == 1
        assert events.first().payload["message"]["order"]["status"] == Booking.STATUS_IN_PROGRESS

    def test_syncing_an_already_terminal_booking_is_a_harmless_no_op(self):
        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")
        booking = self._book_one_leg(trip)
        booking.transition_to(Booking.STATUS_CANCELLED)

        with self._gateway_url_override():
            result = sync_booking_status(booking)

        assert result.status == Booking.STATUS_CANCELLED  # untouched, no BPP call attempted

    def test_sync_trip_tracking_advances_every_leg_of_a_multi_leg_itinerary(self):
        trip = Trip.objects.create(origin="Koramangala", destination="T Nagar")

        with self._gateway_url_override():
            offers = client.search_all_domains(trip.origin, trip.destination)
            auto_leg = next(o for o in offers if o.domain == "ONDC:TRV10" and o.item_id == "auto-standard")
            metro_leg = next(o for o in offers if o.domain == "ONDC:TRV11" and o.bpp_id == "namma-metro")
            result = book_itinerary(trip, [_leg_spec(auto_leg), _leg_spec(metro_leg)])
            assert result.fully_booked is True

            time.sleep(1.2)
            synced = sync_trip_tracking(trip)

        assert len(synced) == 2
        assert all(b.status == Booking.STATUS_IN_PROGRESS for b in synced)
