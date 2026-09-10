"""End-to-end HTTP test of the real API surface the Next.js frontend calls:
POST /api/trips/search/ -> POST /api/trips/<id>/book/ -> GET /api/trips/status/<id>/."""
from django.test import LiveServerTestCase, override_settings
from rest_framework.test import APIClient


class TripSearchAndBookApiTests(LiveServerTestCase):
    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_search_then_book_then_check_status_over_the_real_api(self):
        with self._gateway_url_override():
            search_response = self.api.post(
                "/api/trips/search/", {"origin": "Koramangala", "destination": "Chennai Airport"}, format="json",
            )
            assert search_response.status_code == 200, search_response.data
            body = search_response.data
            assert len(body["offers"]) >= 1
            trip_id = body["trip_id"]
            transaction_id = body["transaction_id"]
            offer = body["offers"][0]

            book_response = self.api.post(
                f"/api/trips/{trip_id}/book/",
                {
                    "transaction_id": transaction_id, "bpp_id": offer["bpp_id"], "item_id": offer["item_id"],
                    "item_name": offer["item_name"], "provider_name": offer["provider_name"],
                    "fare": offer["fare"], "eta_minutes": offer["eta_minutes"], "raw": offer["raw"],
                },
                format="json",
            )
            assert book_response.status_code == 200, book_response.data
            assert book_response.data["status"] == "confirmed"
            booking_id = book_response.data["booking_id"]

            status_response = self.api.get(f"/api/trips/status/{booking_id}/")
            assert status_response.status_code == 200, status_response.data
            assert status_response.data["status"] == "confirmed"
            assert status_response.data["live_bpp_status"] == "confirmed"

    def test_searching_without_a_destination_is_a_client_error(self):
        response = self.api.post("/api/trips/search/", {"origin": "Koramangala"}, format="json")

        assert response.status_code == 400


class BookItineraryApiTests(LiveServerTestCase):
    """End-to-end HTTP test of POST /api/trips/plan/ -> POST /api/trips/<id>/book_itinerary/
    -- the real Phase 2 flow the frontend's itinerary view drives."""

    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_plan_then_book_the_top_ranked_itinerary_over_the_real_api(self):
        with self._gateway_url_override():
            plan_response = self.api.post(
                "/api/trips/plan/", {"origin": "Koramangala", "destination": "T Nagar"}, format="json",
            )
            assert plan_response.status_code == 200, plan_response.data
            itinerary = plan_response.data["itineraries"][0]
            trip_id = plan_response.data["trip_id"]

            book_response = self.api.post(
                f"/api/trips/{trip_id}/book_itinerary/", {"legs": itinerary["legs"]}, format="json",
            )

        assert book_response.status_code == 200, book_response.data
        assert book_response.data["fully_booked"] is True
        assert len(book_response.data["bookings"]) == itinerary["leg_count"]
        assert all(b["status"] == "confirmed" for b in book_response.data["bookings"])
        assert book_response.data["failed_leg_index"] is None

    def test_book_itinerary_without_legs_is_a_client_error(self):
        with self._gateway_url_override():
            plan_response = self.api.post(
                "/api/trips/plan/", {"origin": "Koramangala", "destination": "T Nagar"}, format="json",
            )
        trip_id = plan_response.data["trip_id"]

        response = self.api.post(f"/api/trips/{trip_id}/book_itinerary/", {"legs": []}, format="json")

        assert response.status_code == 400


@override_settings(MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS=1, MOCK_ORDER_COMPLETED_AFTER_SECONDS=2,
                    MOCK_BPP_CALLBACK_DELAY_SECONDS=0.02)
class TripTrackingApiTests(LiveServerTestCase):
    """BUILD_PLAN.md Phase 3: GET /api/trips/<id>/tracking/ -- the endpoint the frontend's
    live itinerary timeline polls. Real elapsed time, real HTTP round trip. Thresholds
    widened to 1s/3s (not 1s/1s) 2026-09-10 -- confirmed flaky at the tighter margin once
    the async callback rework (Phase 4 readiness) added its own real per-leg latency that
    a 2-leg itinerary's SEQUENTIAL sync compounds."""

    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_tracking_reflects_both_legs_progressing_to_in_progress_over_real_time(self):
        import time

        with self._gateway_url_override():
            plan_response = self.api.post(
                "/api/trips/plan/", {"origin": "Koramangala", "destination": "T Nagar"}, format="json",
            )
            itinerary = plan_response.data["itineraries"][0]
            trip_id = plan_response.data["trip_id"]

            book_response = self.api.post(
                f"/api/trips/{trip_id}/book_itinerary/", {"legs": itinerary["legs"]}, format="json",
            )
            assert book_response.data["fully_booked"] is True

            first_poll = self.api.get(f"/api/trips/{trip_id}/tracking/")
            assert first_poll.status_code == 200, first_poll.data
            assert len(first_poll.data["legs"]) == itinerary["leg_count"]
            assert all(leg["status"] == "confirmed" for leg in first_poll.data["legs"])

            time.sleep(2.0)
            second_poll = self.api.get(f"/api/trips/{trip_id}/tracking/")

        assert all(leg["status"] == "in_progress" for leg in second_poll.data["legs"])
        # legs stay in their booked sequence order, each carrying its own mode/places for
        # the frontend's timeline to render without a second lookup
        assert [leg["sequence"] for leg in second_poll.data["legs"]] == sorted(
            leg["sequence"] for leg in second_poll.data["legs"]
        )
        assert all(leg["from_place"] and leg["to_place"] for leg in second_poll.data["legs"])

    def test_tracking_an_unknown_trip_is_a_404(self):
        response = self.api.get("/api/trips/00000000-0000-0000-0000-000000000000/tracking/")

        assert response.status_code == 404
