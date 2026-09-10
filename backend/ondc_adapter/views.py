"""Real inbound Beckn callback endpoints -- on_search/on_select/on_init/on_confirm/
on_status. A real ONDC gateway/BPP POSTs the actual result here (asynchronously, after
the original search()/select()/etc. call already got a bare ACK) -- see models.py's
CallbackRecord docstring and client.py's _await_callback for the other half of this.

Signed by whoever is calling back (a real BPP, or this repo's own mock_bpp) with THEIR
key -- verified here against ONDC_BPP_PUBLIC_KEY, the mirror image of mock_bpp's views
verifying inbound BAP requests against ONDC_BAP_PUBLIC_KEY.
"""
import time

from django.conf import settings
from django.db import OperationalError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .decorators import parse_json_body, require_valid_signature
from .models import CallbackRecord

# 2026-09-10 (BUILD_PLAN.md Phase 4 readiness): making the protocol genuinely async
# surfaced a real concurrency issue that a synchronous mock never could: mock_bpp's
# background callback thread writes CallbackRecord from a different DB connection than
# the original request's own thread, which can be mid-transaction at the same moment.
# SQLite/Turso (both single-writer at the file level) throw a transient
# "database is locked" OperationalError under that contention -- confirmed live via the
# test suite. A short retry is the standard, correct answer (same thing SQLite's own
# busy_timeout does at the driver level) -- NOT a sign the callback failed.
_DB_LOCK_RETRY_ATTEMPTS = 5
_DB_LOCK_RETRY_DELAY_SECONDS = 0.05


def _record_callback(request, action):
    body = parse_json_body(request)
    context = body.get("context", {})
    transaction_id = context.get("transaction_id")
    message_id = context.get("message_id")
    if not transaction_id or not message_id:
        return JsonResponse({"error": "callback missing context.transaction_id/message_id"}, status=400)

    for attempt in range(_DB_LOCK_RETRY_ATTEMPTS):
        try:
            CallbackRecord.objects.update_or_create(
                transaction_id=transaction_id, action=action, message_id=message_id,
                defaults={"payload": body, "received_at": timezone.now()},
            )
            break
        except OperationalError as e:
            is_last_attempt = attempt == _DB_LOCK_RETRY_ATTEMPTS - 1
            if is_last_attempt or "locked" not in str(e):
                raise
            time.sleep(_DB_LOCK_RETRY_DELAY_SECONDS)
    # A real BAP's own on_* response is just an ack of receipt, not another business payload.
    return JsonResponse({"message": {"ack": {"status": "ACK"}}})


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BPP_PUBLIC_KEY)
def on_search(request):
    return _record_callback(request, "on_search")


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BPP_PUBLIC_KEY)
def on_select(request):
    return _record_callback(request, "on_select")


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BPP_PUBLIC_KEY)
def on_init(request):
    return _record_callback(request, "on_init")


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BPP_PUBLIC_KEY)
def on_confirm(request):
    return _record_callback(request, "on_confirm")


@csrf_exempt
@require_POST
@require_valid_signature(lambda: settings.ONDC_BPP_PUBLIC_KEY)
def on_status(request):
    return _record_callback(request, "on_status")
