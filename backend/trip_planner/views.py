from rest_framework.decorators import api_view
from rest_framework.response import Response

from ondc_adapter.client import OndcRequestError

from .services import plan_itineraries, search_trips


@api_view(["POST"])
def search(request):
    """Phase 1: single-domain (TRV10) search -- kept as-is, still backing the original
    /api/trips/search/ + /<id>/book/ single-leg flow. See `plan` below for Phase 2's
    multi-modal itinerary search."""
    origin = request.data.get("origin")
    destination = request.data.get("destination")
    if not origin or not destination:
        return Response({"error": "origin and destination are both required"}, status=400)

    try:
        trip, transaction_id, offers = search_trips(origin, destination)
    except OndcRequestError as e:
        return Response({"error": f"search failed: {e}"}, status=502)

    return Response({
        "trip_id": str(trip.id),
        "transaction_id": transaction_id,
        "offers": [
            {
                "bpp_id": o.bpp_id, "provider_name": o.provider_name,
                "item_id": o.item_id, "item_name": o.item_name,
                "fare": o.fare, "eta_minutes": o.eta_minutes, "raw": o.raw,
            }
            for o in offers
        ],
    })


@api_view(["POST"])
def plan(request):
    """Phase 2: multi-modal, multi-leg itinerary search (trip_planner.planner) across
    TRV10+TRV11+TRV12. cost_weight/time_weight (each 0.0-1.0, default 0.5/0.5) let the
    caller trade cost off against speed -- see planner.rank_itineraries."""
    origin = request.data.get("origin")
    destination = request.data.get("destination")
    if not origin or not destination:
        return Response({"error": "origin and destination are both required"}, status=400)

    try:
        cost_weight = float(request.data.get("cost_weight", 0.5))
        time_weight = float(request.data.get("time_weight", 0.5))
    except (TypeError, ValueError):
        return Response({"error": "cost_weight/time_weight must be numbers"}, status=400)

    try:
        trip, itineraries = plan_itineraries(origin, destination, cost_weight=cost_weight, time_weight=time_weight)
    except OndcRequestError as e:
        return Response({"error": f"search failed: {e}"}, status=502)

    return Response({
        "trip_id": str(trip.id),
        "itineraries": [
            {
                "total_fare": itinerary.total_fare,
                "total_duration_minutes": itinerary.total_duration_minutes,
                "leg_count": itinerary.leg_count,
                "legs": [
                    {
                        "domain": leg.offer.domain, "transaction_id": leg.offer.transaction_id,
                        "bpp_id": leg.offer.bpp_id, "provider_name": leg.offer.provider_name,
                        "item_id": leg.offer.item_id, "item_name": leg.offer.item_name,
                        "fare": leg.offer.fare, "eta_minutes": leg.offer.eta_minutes,
                        "mode": leg.mode, "from_place": leg.from_place, "to_place": leg.to_place,
                        "raw": leg.offer.raw,
                    }
                    for leg in itinerary.legs
                ],
            }
            for itinerary in itineraries
        ],
    })
