"""A small, fixed TRV10 (ride-hailing) catalog the mock BPP quotes from -- deliberately
static/deterministic rather than "realistic" pricing logic, since this simulator's only
job is to exercise the real Beckn message shapes and the signing round-trip end to end,
not to model actual fares. See BUILD_PLAN.md Phase 1: single-domain (TRV10) only."""

PROVIDERS = [
    {
        "id": "namma-yatri",
        "name": "Namma Yatri",
        "items": [
            {"id": "auto-standard", "name": "Auto", "fare": "129.00", "eta_minutes": 4},
            {"id": "cab-sedan", "name": "Sedan", "fare": "289.00", "eta_minutes": 7},
        ],
    },
    {
        "id": "yatri-sathi",
        "name": "Yatri Sathi",
        "items": [
            {"id": "bike-taxi", "name": "Bike Taxi", "fare": "79.00", "eta_minutes": 3},
            {"id": "black-yellow-taxi", "name": "Black & Yellow Taxi", "fare": "245.50", "eta_minutes": 6},
        ],
    },
]


def all_offers():
    """Flattens PROVIDERS into (provider_id, provider_name, item) tuples."""
    for provider in PROVIDERS:
        for item in provider["items"]:
            yield provider["id"], provider["name"], item


def find_item(provider_id, item_id):
    for provider in PROVIDERS:
        if provider["id"] != provider_id:
            continue
        for item in provider["items"]:
            if item["id"] == item_id:
                return provider, item
    return None, None
