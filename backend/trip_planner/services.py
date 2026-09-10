"""Phase 1 scope (BUILD_PLAN.md): single-domain (TRV10 ride-hailing) search only.
Phase 2's leg-graph / multi-objective itinerary search over TRV10+TRV11+TRV12 belongs
here later -- deliberately not stubbed out yet, so this file doesn't carry
half-finished abstractions for a search algorithm that isn't built."""
from bookings.models import Trip
from ondc_adapter import client


def search_trips(origin, destination):
    """Creates a Trip record and returns (trip, transaction_id, offers) -- the caller
    (trip_planner's view) is responsible for handing transaction_id + the chosen offer
    back to bookings.services.book_leg later; nothing is persisted as a TripLeg until
    the user actually picks one (see bookings/services.py)."""
    trip = Trip.objects.create(origin=origin, destination=destination)
    offers, transaction_id = client.search(origin, destination)
    return trip, transaction_id, offers
