from rest_framework.decorators import api_view
from rest_framework.response import Response

from ondc_adapter.client import OndcRequestError

from .services import search_trips


@api_view(["POST"])
def search(request):
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
