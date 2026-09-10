"""Per-domain TRV10/TRV11/TRV12 mock route catalogs -- deliberately static/deterministic
fares+durations (not "realistic" pricing), since this simulator's only job is to exercise
the real Beckn message shapes + signing round-trip end to end, not model actual fares.

BUILD_PLAN.md Phase 2: routes now connect a small, fixed set of NAMED PLACES (not
arbitrary geography -- see README's demo place names) across all three domains, so
trip_planner's leg-graph search has real multi-leg itineraries to compose across
independent simulated sellers, e.g. Koramangala -> MG Road Metro (TRV10 auto) ->
Bengaluru Bus Terminal (TRV11 metro) -> Chennai Bus Terminal (TRV12 intercity bus) ->
Chennai Central Metro (TRV11 metro) -> T Nagar (TRV10 bike-taxi), as an alternative to
a costlier-but-faster Koramangala -> Bengaluru Airport -> Chennai Airport -> T Nagar
route via TRV12 flight. Phase 1's TRV10-only shape (id/name/fare/eta_minutes) is
extended with from_place/to_place/mode -- both fields ondc_adapter.client needs to
build trip_planner's graph, on top of the same signed request/response shapes."""

ROUTES = {
    "ONDC:TRV10": [
        {"bpp_id": "namma-yatri", "provider_name": "Namma Yatri", "item_id": "auto-standard",
         "item_name": "Auto", "from_place": "Koramangala", "to_place": "MG Road Metro",
         "fare": "90.00", "eta_minutes": 12, "mode": "auto"},
        {"bpp_id": "namma-yatri", "provider_name": "Namma Yatri", "item_id": "cab-sedan",
         "item_name": "Sedan", "from_place": "Koramangala", "to_place": "Bengaluru Bus Terminal",
         "fare": "350.00", "eta_minutes": 20, "mode": "cab"},
        {"bpp_id": "namma-yatri", "provider_name": "Namma Yatri", "item_id": "cab-airport",
         "item_name": "Sedan (Airport)", "from_place": "Koramangala", "to_place": "Bengaluru Airport",
         "fare": "650.00", "eta_minutes": 45, "mode": "cab"},
        {"bpp_id": "yatri-sathi", "provider_name": "Yatri Sathi", "item_id": "bike-taxi",
         "item_name": "Bike Taxi", "from_place": "Chennai Central Metro", "to_place": "T Nagar",
         "fare": "60.00", "eta_minutes": 10, "mode": "bike_taxi"},
        {"bpp_id": "yatri-sathi", "provider_name": "Yatri Sathi", "item_id": "black-yellow-taxi",
         "item_name": "Black & Yellow Taxi", "from_place": "Chennai Bus Terminal", "to_place": "T Nagar",
         "fare": "180.00", "eta_minutes": 20, "mode": "cab"},
        {"bpp_id": "yatri-sathi", "provider_name": "Yatri Sathi", "item_id": "cab-airport-chn",
         "item_name": "Sedan (Airport)", "from_place": "Chennai Airport", "to_place": "T Nagar",
         "fare": "400.00", "eta_minutes": 30, "mode": "cab"},
    ],
    "ONDC:TRV11": [
        {"bpp_id": "namma-metro", "provider_name": "Namma Metro", "item_id": "metro-standard",
         "item_name": "Metro", "from_place": "MG Road Metro", "to_place": "Bengaluru Bus Terminal",
         "fare": "40.00", "eta_minutes": 25, "mode": "metro"},
        {"bpp_id": "chennai-metro", "provider_name": "Chennai Metro Rail", "item_id": "metro-standard",
         "item_name": "Metro", "from_place": "Chennai Bus Terminal", "to_place": "Chennai Central Metro",
         "fare": "35.00", "eta_minutes": 20, "mode": "metro"},
    ],
    "ONDC:TRV12": [
        {"bpp_id": "intrcity-smartbus", "provider_name": "IntrCity SmartBus", "item_id": "ac-sleeper",
         "item_name": "AC Sleeper", "from_place": "Bengaluru Bus Terminal", "to_place": "Chennai Bus Terminal",
         "fare": "899.00", "eta_minutes": 360, "mode": "intercity_bus"},
        {"bpp_id": "indigo", "provider_name": "IndiGo", "item_id": "economy",
         "item_name": "Economy", "from_place": "Bengaluru Airport", "to_place": "Chennai Airport",
         "fare": "3499.00", "eta_minutes": 75, "mode": "flight"},
    ],
}


def all_offers(domain):
    """Flattens ROUTES[domain] into (provider_id, provider_name, route) tuples -- same
    contract as Phase 1's domain-less all_offers(), now domain-scoped. Returns nothing
    for an unknown domain rather than raising -- mirrors find_item's not-found handling."""
    for route in ROUTES.get(domain, []):
        yield route["bpp_id"], route["provider_name"], route


def find_item(domain, provider_id, item_id):
    """Returns ({"name": provider_name}, route) for a real match, or (None, None) --
    the provider dict is intentionally minimal since callers only ever read ["name"]."""
    for route in ROUTES.get(domain, []):
        if route["bpp_id"] == provider_id and route["item_id"] == item_id:
            return {"name": route["provider_name"]}, route
    return None, None
