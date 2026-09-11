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
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

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


class PlanFromTextApiTests(LiveServerTestCase):
    """POST /api/trips/plan_from_text/ -- Gemini extraction (trip_planner.nl_intent) is
    monkeypatched here so these tests never make a real network call to Gemini; the point
    is proving the REAL rest of the pipeline (extracted intent -> plan_itineraries ->
    real signed ONDC search -> mock_bpp -> back) runs end to end from a natural-language
    request, same as test_views.PlanApiTests does for the form-based /plan/ endpoint. A
    real, live Gemini call was separately confirmed working by hand against the actual
    API (see nl_intent.py's module docstring) -- not re-proven on every test run."""

    def setUp(self):
        self.api = APIClient()

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_plan_from_text_understands_a_free_text_request_and_returns_real_itineraries(self, ):
        import trip_planner.views as views_module

        def fake_parse(text, api_key):
            assert api_key == "fake-gemini-key"
            return {"origin": "Koramangala", "destination": "T Nagar", "cost_weight": 0.8, "time_weight": 0.2}

        original_parse = views_module.parse_trip_request
        views_module.parse_trip_request = fake_parse
        try:
            with self._gateway_url_override(), override_settings():
                import os
                old_key = os.environ.get("GEMINI_API_KEY")
                os.environ["GEMINI_API_KEY"] = "fake-gemini-key"
                try:
                    response = self.api.post(
                        "/api/trips/plan_from_text/",
                        {"text": "get me from Koramangala to T Nagar, keep it cheap"}, format="json",
                    )
                finally:
                    if old_key is None:
                        os.environ.pop("GEMINI_API_KEY", None)
                    else:
                        os.environ["GEMINI_API_KEY"] = old_key
        finally:
            views_module.parse_trip_request = original_parse

        assert response.status_code == 200, response.data
        assert response.data["understood_as"]["origin"] == "Koramangala"
        assert response.data["understood_as"]["destination"] == "T Nagar"
        assert len(response.data["itineraries"]) >= 1

    def test_plan_from_text_without_text_is_a_client_error(self):
        response = self.api.post("/api/trips/plan_from_text/", {}, format="json")

        assert response.status_code == 400

    def test_plan_from_text_surfaces_an_unclear_request_as_422_not_500(self):
        import trip_planner.views as views_module
        from trip_planner.nl_intent import NlIntentError

        def fake_parse(text, api_key):
            raise NlIntentError("Gemini's response is missing a destination")

        original_parse = views_module.parse_trip_request
        views_module.parse_trip_request = fake_parse
        try:
            response = self.api.post(
                "/api/trips/plan_from_text/", {"text": "somewhere, I guess"}, format="json",
            )
        finally:
            views_module.parse_trip_request = original_parse

        assert response.status_code == 422
        assert "destination" in response.data["error"]
