from django.test import LiveServerTestCase, override_settings

from bookings.models import Booking, Trip
from bookings.services import book_leg
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
