import os

from rest_framework.decorators import api_view
from rest_framework.response import Response

from ondc_adapter.client import OndcRequestError

from .nl_intent import NlIntentError, parse_trip_request
from .services import plan_itineraries, search_trips


def _serialize_itineraries(itineraries):
    """Shared by plan/plan_from_text -- both return the exact same itinerary shape,
    since plan_from_text is just a natural-language front door onto the same planner."""
    return [
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
    ]


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
        "itineraries": _serialize_itineraries(itineraries),
    })


@api_view(["POST"])
def plan_from_text(request):
    """Natural-language front door onto `plan` above: "get me from Koramangala to
    T Nagar tomorrow morning, keep it cheap" instead of a rigid origin/destination/
    weights form. Gemini (trip_planner.nl_intent) extracts the structured request, which
    then flows through the exact same plan_itineraries() as the form-based /plan/
    endpoint -- nothing about ONDC search/booking knows or cares that this leg started
    as free text."""
    text = request.data.get("text")
    if not text:
        return Response({"error": "text is required"}, status=400)

    try:
        intent = parse_trip_request(text, api_key=os.environ.get("GEMINI_API_KEY"))
    except NlIntentError as e:
        return Response({"error": f"could not understand that request: {e}"}, status=422)

    try:
        trip, itineraries = plan_itineraries(
            intent["origin"], intent["destination"],
            cost_weight=intent["cost_weight"], time_weight=intent["time_weight"],
        )
    except OndcRequestError as e:
        return Response({"error": f"search failed: {e}"}, status=502)

    return Response({
        "trip_id": str(trip.id),
        "understood_as": intent,
        "itineraries": _serialize_itineraries(itineraries),
    })
