"""End-to-end HTTP test of the real API surface the Next.js frontend calls:
POST /api/trips/search/ -> POST /api/trips/<id>/book/ -> GET /api/trips/status/<id>/."""
from django.test import LiveServerTestCase, override_settings
from rest_framework.test import APIClient


class TripSearchAndBookApiTests(LiveServerTestCase):
    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

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
