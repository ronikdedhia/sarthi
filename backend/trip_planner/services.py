"""Phase 1 scope (BUILD_PLAN.md) was single-domain (TRV10 ride-hailing) search only --
search_trips below is that original entry point, kept as-is (still used by the existing
/api/trips/search/ + /<id>/book/ single-leg flow and its tests).

Phase 2 adds plan_itineraries: the real leg-graph / multi-objective itinerary search over
TRV10+TRV11+TRV12 (trip_planner.planner), fed by ondc_adapter.client.search_all_domains."""
from bookings.models import Trip
from ondc_adapter import client

from .planner import LegOption, build_graph, find_itinerary_paths, rank_itineraries


def search_trips(origin, destination):
    """Creates a Trip record and returns (trip, transaction_id, offers) -- the caller
    (trip_planner's view) is responsible for handing transaction_id + the chosen offer
    back to bookings.services.book_leg later; nothing is persisted as a TripLeg until
    the user actually picks one (see bookings/services.py)."""
    trip = Trip.objects.create(origin=origin, destination=destination)
    offers, transaction_id = client.search(origin, destination)
    return trip, transaction_id, offers


def plan_itineraries(origin, destination, cost_weight=0.5, time_weight=0.5, max_legs=4):
    """Creates a Trip record and returns (trip, list[Itinerary]) -- BUILD_PLAN.md Phase 2's
    multi-modal, multi-leg search. Fans out one signed search per domain
    (ondc_adapter.client.search_all_domains), builds the candidate leg graph from every
    returned Offer (mock_bpp's route catalog decides what's actually reachable from
    `origin`), and ranks every simple path to `destination` by the given cost/time
    trade-off. An origin/destination pair with no connecting route in the demo catalog
    (see README's known place names) legitimately returns an empty itinerary list --
    that's not an error, it just means trip_planner has nothing to offer for that pair
    yet, same as a real ONDC search returning zero providers for an unserved route."""
    trip = Trip.objects.create(origin=origin, destination=destination)
    offers = client.search_all_domains(origin, destination)

    leg_options = [
        LegOption(
            from_place=offer.from_place, to_place=offer.to_place, fare=float(offer.fare),
            duration_minutes=offer.eta_minutes, mode=offer.mode, offer=offer,
        )
        for offer in offers
    ]
    graph = build_graph(leg_options)
    paths = find_itinerary_paths(graph, origin, destination, max_legs=max_legs)
    itineraries = rank_itineraries(paths, cost_weight=cost_weight, time_weight=time_weight)
    return trip, itineraries
