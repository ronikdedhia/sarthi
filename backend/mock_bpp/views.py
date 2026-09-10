"""A simulated ONDC TRV10/11/12 seller app -- see this module's package docstring plan in
FEASIBILITY_RESEARCH.md #3 for why this exists instead of the real ONDC-Official/
ondc-mock-server: no registry approval exists yet to point at a real gateway, and this
repo's ondc_adapter needs *something* that speaks the real signed Beckn message shapes to
build and test against today.

2026-09-10 (BUILD_PLAN.md Phase 4 readiness): this used to respond SYNCHRONOUSLY in the
same HTTP response -- a real simplification when this file was first written (a single
simulated BPP in one process has no gateway fan-out to wait on), but it meant
ondc_adapter.client's "swap the gateway URL for a real one" claim didn't actually survive
contact with the real, asynchronous Beckn protocol (a real BPP ACKs immediately and POSTs
the real result back to the BAP's own callback URL later). Now genuinely async: every
view below signs and returns a bare ACK immediately, then a background thread builds the
real on_search/on_select/on_init/on_confirm/on_status payload, waits
settings.MOCK_BPP_CALLBACK_DELAY_SECONDS (real, not zero, so the round trip is genuinely
exercised), and POSTs it to the BAP's own bap_uri from the original request's context --
exactly the shape a real gateway/BPP would use, just simulated in-process.
"""
import json
import threading
import time
import uuid

import requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ondc_adapter.decorators import parse_json_body, require_valid_signature
from ondc_adapter.signing import build_authorization_header

from . import store
from .catalog import all_offers, find_item


def _sign(payload):
    """Returns (body_bytes, auth_header) -- shared by both the synchronous ACK and the
    later async callback POST, since both are messages BPP signs with its own key."""
    body_bytes = json.dumps(payload).encode()
    header = build_authorization_header(
        body_bytes, settings.ONDC_BPP_PRIVATE_KEY, settings.ONDC_BPP_SUBSCRIBER_ID, settings.ONDC_BPP_KEY_ID,
    )
    return body_bytes, header


def _ack_response(context):
    payload = {"message": {"ack": {"status": "ACK"}}, "context": context}
    body_bytes, header = _sign(payload)
    response = JsonResponse(payload)
    response["Authorization"] = header
    return response


def _send_callback_soon(bap_uri, action, payload):
    """Fires the real on_<action> callback in a background thread after a deliberate,
    real (not zero) delay -- see this module's docstring. Best-effort: a real gateway
    doesn't block its own ACK on whether the callback POST eventually succeeds, and
    neither does this; a failed/unreachable bap_uri just means client.py's
    _await_callback times out, same as it would for a real unreachable BAP."""

    def _worker():
        time.sleep(settings.MOCK_BPP_CALLBACK_DELAY_SECONDS)
        body_bytes, header = _sign(payload)
        try:
            requests.post(
                f"{bap_uri}/{action}/", data=body_bytes,
                headers={"Content-Type": "application/json", "Authorization": header},
                timeout=10,
            )
        except requests.RequestException:
            pass

    threading.Thread(target=_worker, daemon=True).start()


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def search(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    domain = context.get("domain", "ONDC:TRV10")
    bap_uri = context.get("bap_uri")

    providers = {}
    for provider_id, provider_name, route in all_offers(domain):
        providers.setdefault(provider_id, {"id": provider_id, "descriptor": {"name": provider_name}, "items": []})
        providers[provider_id]["items"].append({
            "id": route["item_id"],
            "descriptor": {"name": route["item_name"]},
            "price": {"currency": "INR", "value": route["fare"]},
            "time": {"duration": f"PT{route['eta_minutes']}M"},
            # Pragmatic simplification, not strict Beckn (a real BPP would encode this via
            # category_id/fulfillment.type conventions) -- mode + fulfillment start/end are
            # exactly what ondc_adapter.client needs to feed trip_planner's leg-graph search
            # candidate edges across domains. See this module's docstring.
            "mode": route["mode"],
            "fulfillment": {
                "start": {"location": {"descriptor": {"name": route["from_place"]}}},
                "end": {"location": {"descriptor": {"name": route["to_place"]}}},
            },
        })

    on_search_payload = {
        "context": {**context, "action": "on_search"},
        "message": {"catalog": {"bpp/providers": list(providers.values())}},
    }
    if bap_uri:
        _send_callback_soon(bap_uri, "on_search", on_search_payload)
    return _ack_response(context)


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def select(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    domain = context.get("domain", "ONDC:TRV10")
    bap_uri = context.get("bap_uri")
    transaction_id = context.get("transaction_id")
    order = body.get("message", {}).get("order", {})
    provider_id = order.get("provider", {}).get("id")
    item_id = order.get("items", [{}])[0].get("id")

    provider, route = find_item(domain, provider_id, item_id)
    if route is None:
        return JsonResponse({"error": f"no such item {provider_id}/{item_id} in domain {domain}"}, status=400)

    store.remember_selection(transaction_id, domain, provider_id, item_id)

    on_select_payload = {
        "context": {**context, "action": "on_select"},
        "message": {"order": {
            "provider": {"id": provider_id, "descriptor": {"name": provider["name"]}},
            "items": [{"id": item_id, "descriptor": {"name": route["item_name"]}}],
            "quote": {"price": {"currency": "INR", "value": route["fare"]}},
        }},
    }
    if bap_uri:
        _send_callback_soon(bap_uri, "on_select", on_select_payload)
    return _ack_response(context)


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def init(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    bap_uri = context.get("bap_uri")
    transaction_id = context.get("transaction_id")

    if store.get_order(transaction_id) is None:
        return JsonResponse({"error": f"no prior select() for transaction {transaction_id}"}, status=400)
    store.mark_initiated(transaction_id)

    on_init_payload = {
        "context": {**context, "action": "on_init"},
        "message": {"order": {"transaction_id": transaction_id, "status": "initiated"}},
    }
    if bap_uri:
        _send_callback_soon(bap_uri, "on_init", on_init_payload)
    return _ack_response(context)


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def confirm(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    bap_uri = context.get("bap_uri")
    transaction_id = context.get("transaction_id")

    order = store.get_order(transaction_id)
    if order is None or order["status"] != "initiated":
        return JsonResponse(
            {"error": f"transaction {transaction_id} not in an initiated state (found: {order})"}, status=400,
        )

    order_id = f"order-{uuid.uuid4().hex[:12]}"
    store.confirm_order(transaction_id, order_id)

    on_confirm_payload = {
        "context": {**context, "action": "on_confirm"},
        "message": {"order": {"id": order_id, "transaction_id": transaction_id, "status": "confirmed"}},
    }
    if bap_uri:
        _send_callback_soon(bap_uri, "on_confirm", on_confirm_payload)
    return _ack_response(context)


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BAP_PUBLIC_KEY)
def status(request):
    body = parse_json_body(request)
    context = body.get("context", {})
    bap_uri = context.get("bap_uri")
    transaction_id = context.get("transaction_id")

    order = store.get_order(transaction_id)
    if order is None:
        return JsonResponse({"error": f"no such transaction {transaction_id}"}, status=404)

    on_status_payload = {
        "context": {**context, "action": "on_status"},
        "message": {"order": {"transaction_id": transaction_id, "status": order["status"]}},
    }
    if bap_uri:
        _send_callback_soon(bap_uri, "on_status", on_status_payload)
    return _ack_response(context)
