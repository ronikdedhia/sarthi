from rest_framework.decorators import api_view
from rest_framework.response import Response

from ondc_adapter import client as ondc_client
from ondc_adapter.client import OndcRequestError

from .models import Booking, Trip
from .services import BookingFailedError, book_leg


@api_view(["POST"])
def book(request, trip_id):
    try:
        trip = Trip.objects.get(pk=trip_id)
    except Trip.DoesNotExist:
        return Response({"error": f"no such trip {trip_id}"}, status=404)

    data = request.data
    required = ["transaction_id", "bpp_id", "item_id", "item_name", "provider_name", "fare", "eta_minutes"]
    missing = [f for f in required if f not in data]
    if missing:
        return Response({"error": f"missing field(s): {missing}"}, status=400)

    try:
        booking = book_leg(
            trip, data["transaction_id"], data["bpp_id"], data["item_id"], data["item_name"],
            data["provider_name"], data["fare"], data["eta_minutes"], data.get("raw", {}),
        )
    except BookingFailedError as e:
        return Response(
            {"error": str(e), "step": e.step, "booking_id": str(e.booking.id), "status": e.booking.status},
            status=502,
        )

    return Response({
        "booking_id": str(booking.id), "status": booking.status, "order_id": booking.ondc_order_id,
    })


@api_view(["GET"])
def booking_status(request, booking_id):
    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"error": f"no such booking {booking_id}"}, status=404)

    # Best-effort live refresh from the (mock) BPP — falls back to the last-known DB
    # state if the live status call fails, same "never crash on a flaky ONDC call"
    # posture ARCHITECTURE.md calls for elsewhere.
    try:
        live_status, _ = ondc_client.get_status(booking.ondc_transaction_id)
    except OndcRequestError:
        live_status = None

    return Response({
        "booking_id": str(booking.id),
        "status": booking.status,
        "order_id": booking.ondc_order_id,
        "live_bpp_status": live_status,
    })
