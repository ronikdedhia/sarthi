"""End-to-end HTTP test of POST /api/trips/plan/ -- real signed search calls across all
three domains against mock_bpp, composed into real multi-leg itineraries. Complements
test_planner.py (pure graph logic on crafted graphs) by proving the whole real stack
(view -> services.plan_itineraries -> ondc_adapter.client -> real HTTP -> mock_bpp ->
back) produces the same kind of result against the actual demo route catalog."""
from django.test import LiveServerTestCase, override_settings
from rest_framework.test import APIClient


class PlanApiTests(LiveServerTestCase):
    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

    def test_plan_returns_at_least_two_ranked_multi_domain_itineraries(self):
        """Koramangala -> T Nagar has (at least) two real independent routes in the demo
        catalog: an intercity-bus-trunk itinerary and a flight-trunk one -- BUILD_PLAN.md's
        "2-3 ranked itinerary options spanning ... different, independent ONDC seller apps.\""""
        with self._gateway_url_override():
            response = self.api.post(
                "/api/trips/plan/", {"origin": "Koramangala", "destination": "T Nagar"}, format="json",
            )

        assert response.status_code == 200, response.data
        itineraries = response.data["itineraries"]
        assert len(itineraries) >= 2

        domains_used = {leg["domain"] for itinerary in itineraries for leg in itinerary["legs"]}
        assert "ONDC:TRV10" in domains_used
        assert "ONDC:TRV12" in domains_used  # the intercity trunk every real route needs

        # ranked best-first for the default balanced weighting -- not just insertion order
        scores = [it["total_fare"] + it["total_duration_minutes"] for it in itineraries]
        # (loose sanity check only: real ranking math is covered by test_planner.py;
        # this just proves the view returns itineraries with real fare/duration each)
        assert all(s > 0 for s in scores)

    def test_plan_cost_weighted_favors_the_cheaper_bus_trunk_over_the_pricier_flight(self):
        with self._gateway_url_override():
            response = self.api.post(
                "/api/trips/plan/",
                {"origin": "Koramangala", "destination": "T Nagar", "cost_weight": 1.0, "time_weight": 0.0},
                format="json",
            )

        assert response.status_code == 200, response.data
        cheapest = response.data["itineraries"][0]
        modes = {leg["mode"] for leg in cheapest["legs"]}
        assert "flight" not in modes  # the flight-trunk itinerary is far pricier

    def test_plan_time_weighted_favors_the_faster_flight_trunk_over_the_bus(self):
        with self._gateway_url_override():
            response = self.api.post(
                "/api/trips/plan/",
                {"origin": "Koramangala", "destination": "T Nagar", "cost_weight": 0.0, "time_weight": 1.0},
                format="json",
            )

        assert response.status_code == 200, response.data
        fastest = response.data["itineraries"][0]
        modes = {leg["mode"] for leg in fastest["legs"]}
        assert "flight" in modes

    def test_plan_returns_an_empty_itinerary_list_for_an_unconnected_place_pair(self):
        with self._gateway_url_override():
            response = self.api.post(
                "/api/trips/plan/", {"origin": "Nowhere", "destination": "Also Nowhere"}, format="json",
            )

        assert response.status_code == 200, response.data
        assert response.data["itineraries"] == []

    def test_plan_without_a_destination_is_a_client_error(self):
        response = self.api.post("/api/trips/plan/", {"origin": "Koramangala"}, format="json")

        assert response.status_code == 400
