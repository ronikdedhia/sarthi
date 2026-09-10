"""BUILD_PLAN.md Phase 3's background worker (`python manage.py poll_bookings`) --
tests exercise run_poll_pass directly (one real pass) rather than the infinite loop
Command.handle wraps it in, per its own docstring."""
import time

from django.test import LiveServerTestCase, override_settings

from bookings.management.commands.poll_bookings import run_poll_pass
from bookings.models import Booking, Trip
from bookings.services import book_leg
from ondc_adapter import client


@override_settings(MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS=1, MOCK_ORDER_COMPLETED_AFTER_SECONDS=1)
class PollBookingsCommandTests(LiveServerTestCase):
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

    def test_a_poll_pass_advances_a_confirmed_booking_and_returns_how_many_it_checked(self):
        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")
        booking = self._book_one_leg(trip)

        with self._gateway_url_override():
            time.sleep(1.2)
            checked = run_poll_pass()

        assert checked == 1
        assert Booking.objects.get(pk=booking.pk).status == Booking.STATUS_IN_PROGRESS

    def test_a_poll_pass_skips_terminal_bookings_entirely(self):
        trip = Trip.objects.create(origin="Koramangala", destination="Chennai Airport")
        booking = self._book_one_leg(trip)
        booking.transition_to(Booking.STATUS_CANCELLED)

        with self._gateway_url_override():
            checked = run_poll_pass()

        assert checked == 0

    def test_a_poll_pass_with_nothing_to_check_returns_zero_without_error(self):
        assert run_poll_pass() == 0
