"""A simulated ONDC TRV10 (ride-hailing) seller app -- see this module's package
docstring plan in FEASIBILITY_RESEARCH.md #3 for why this exists instead of the real
ONDC-Official/ondc-mock-server: no registry approval exists yet to point at a real
gateway, and this repo's ondc_adapter needs *something* that speaks the real signed
Beckn message shapes to build and test against today.

Deliberate simplification vs. the real (fully async, gateway-routed) protocol: this
returns each response SYNCHRONOUSLY in the same HTTP response, rather than ACKing
immediately and POSTing an on_search/on_select/... callback back to the BAP's own
endpoint. A real BPP is architecturally async because a gateway fans one /search out to
many BPPs that respond on their own schedule; a single simulated BPP in the same process
has no such fan-out to wait on, so synchronous keeps this simulator's own moving parts
honest rather than adding an async dance that isn't modeling anything real here. Swapping
this for the real network later only touches ondc_adapter.client's internals (per
ARCHITECTURE.md's isolation principle) -- everything upstream of it already deals in
"call search(), get offers back," which is what a truly async client would look like from
the outside too.
"""
import json
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ondc_adapter.decorators import parse_json_body, require_valid_signature
from ondc_adapter.signing import build_authorization_header

from . import store
from .catalog import all_offers, find_item


def _sign_response(payload):
    body_bytes = json.dumps(payload).encode()
    header = build_authorization_header(
        body_bytes, settings.ONDC_BPP_PRIVATE_KEY, settings.ONDC_BPP_SUBSCRIBER_ID, settings.ONDC_BPP_KEY_ID,
    )
    response = JsonResponse(payload)
    response["Authorization"] = header
    return response


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def search(request):
    body = parse_json_body(request)
    context = body.get("context", {})

    providers = {}
    for provider_id, provider_name, item in all_offers():
        providers.setdefault(provider_id, {"id": provider_id, "descriptor": {"name": provider_name}, "items": []})
        providers[provider_id]["items"].append({
            "id": item["id"],
            "descriptor": {"name": item["name"]},
            "price": {"currency": "INR", "value": item["fare"]},
            "time": {"duration": f"PT{item['eta_minutes']}M"},
        })

    return _sign_response({
        "context": {**context, "action": "on_search"},
        "message": {"catalog": {"bpp/providers": list(providers.values())}},
    })


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def select(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    transaction_id = context.get("transaction_id")
    order = body.get("message", {}).get("order", {})
    provider_id = order.get("provider", {}).get("id")
    item_id = order.get("items", [{}])[0].get("id")

    provider, item = find_item(provider_id, item_id)
    if item is None:
        return JsonResponse({"error": f"no such item {provider_id}/{item_id}"}, status=400)

    store.remember_selection(transaction_id, provider_id, item_id)

    return _sign_response({
        "context": {**context, "action": "on_select"},
        "message": {"order": {
            "provider": {"id": provider_id, "descriptor": {"name": provider["name"]}},
            "items": [{"id": item_id, "descriptor": {"name": item["name"]}}],
            "quote": {"price": {"currency": "INR", "value": item["fare"]}},
        }},
    })


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def init(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    transaction_id = context.get("transaction_id")

    if store.get_order(transaction_id) is None:
        return JsonResponse({"error": f"no prior select() for transaction {transaction_id}"}, status=400)
    store.mark_initiated(transaction_id)

    return _sign_response({
        "context": {**context, "action": "on_init"},
        "message": {"order": {"transaction_id": transaction_id, "status": "initiated"}},
    })


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def confirm(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    transaction_id = context.get("transaction_id")

    order = store.get_order(transaction_id)
    if order is None or order["status"] != "initiated":
        return JsonResponse(
            {"error": f"transaction {transaction_id} not in an initiated state (found: {order})"}, status=400,
        )

    order_id = f"order-{uuid.uuid4().hex[:12]}"
    store.confirm_order(transaction_id, order_id)

    return _sign_response({
        "context": {**context, "action": "on_confirm"},
        "message": {"order": {"id": order_id, "transaction_id": transaction_id, "status": "confirmed"}},
    })


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def status(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    transaction_id = context.get("transaction_id")

    order = store.get_order(transaction_id)
    if order is None:
        return JsonResponse({"error": f"no such transaction {transaction_id}"}, status=404)

    return _sign_response({
        "context": {**context, "action": "on_status"},
        "message": {"order": {"transaction_id": transaction_id, "status": order["status"]}},
    })
