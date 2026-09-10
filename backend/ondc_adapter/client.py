"""The ONE place the rest of Sarthi talks to ONDC/Beckn through -- ARCHITECTURE.md's
isolation principle: "everything else talks to it through a clean internal interface
... so swapping mock server for real registry later is a config change, not a rewrite."

Today ONDC_GATEWAY_BASE_URL points at this same repo's mock_bpp app (see
FEASIBILITY_RESEARCH.md #2-3 for why: real registry/NP approval is a manual process this
project doesn't have yet). Every call is still really signed and really verified against
the mock BPP's response signature -- nothing here is faked at the protocol level, only
the network topology (one simulated seller instead of a gateway fanning out to many)
is simplified for local dev.

2026-09-10 (BUILD_PLAN.md Phase 4 readiness): this module used to send a request and
parse the real result straight out of the SAME HTTP response -- fine against mock_bpp's
original synchronous simplification, but not how the real ONDC/Beckn protocol actually
works, and NOT something "swap the gateway URL" alone would have survived. Real BAP/BPP
calls are asynchronous: a `search` (etc.) POST gets a bare ACK immediately, and the real
result arrives later as a SEPARATE POST (`on_search`, etc.) to the BAP's own registered
callback URL (`context.bap_uri`), correlated by `transaction_id`. Every function below now
genuinely does that -- POST, verify the ACK, then poll ondc_adapter.models.CallbackRecord
(populated by ondc_adapter/views.py's on_* endpoints) for the real payload -- so this
module's *external* behavior (call search(), get offers back) hasn't changed, but it
would now actually survive being pointed at a real gateway, which the old
synchronous-only version would not have.
"""
import dataclasses
import json
import time
import uuid
from datetime import datetime, timezone

import requests
from django.conf import settings

from .models import CallbackRecord
from .signing import SignatureVerificationError, build_authorization_header, verify_authorization_header

REQUEST_TIMEOUT_SECONDS = 10

# BUILD_PLAN.md Phase 1 scope was ONDC:TRV10 (ride-hailing) only, hardcoded into every
# context. Phase 2 adds TRV11 (metro/intracity bus) and TRV12 (intercity bus/flight) --
# every function below now takes an optional `domain` defaulting to TRV10, so every
# existing Phase 1 call site (and its tests) keeps behaving exactly as before.
DEFAULT_DOMAIN = "ONDC:TRV10"
ALL_DOMAINS = ("ONDC:TRV10", "ONDC:TRV11", "ONDC:TRV12")


class OndcRequestError(Exception):
    """Raised for a non-2xx response, an unsigned/invalid response, or a transport
    failure -- callers should never have to distinguish those cases from a bare
    requests.RequestException, since "did the network call actually work" is the one
    question that matters here."""


@dataclasses.dataclass(frozen=True)
class Offer:
    """One bookable option from a search -- the shape trip_planner works with, so it
    never has to know Beckn's own nested provider/item/price JSON structure.

    domain/transaction_id are carried on the Offer itself (not just returned alongside
    it) so a Phase 2 itinerary spanning several domains' search() calls can select/init/
    confirm each leg independently -- each leg's own domain+transaction_id, not a single
    shared one. from_place/to_place/mode are what trip_planner's leg-graph search uses
    to compose multi-leg itineraries across domains (see mock_bpp/catalog.py)."""

    bpp_id: str
    provider_name: str
    item_id: str
    item_name: str
    fare: str
    eta_minutes: int
    raw: dict
    domain: str
    transaction_id: str
    from_place: str
    to_place: str
    mode: str


def _new_transaction_id():
    return uuid.uuid4().hex


def _build_context(action, transaction_id, domain, message_id=None):
    return {
        "domain": domain,
        "action": action,
        "bap_id": settings.ONDC_BAP_SUBSCRIBER_ID,
        # Real Beckn field: where the gateway/BPP sends this request's own on_<action>
        # callback -- see ondc_adapter/urls.py and models.CallbackRecord. Must be a real,
        # externally-reachable URL for real registry use (settings.SARTHI_BASE_URL).
        "bap_uri": f"{settings.SARTHI_BASE_URL}/ondc_adapter",
        "bpp_id": settings.ONDC_BPP_SUBSCRIBER_ID,
        "transaction_id": transaction_id,
        "message_id": message_id or uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _post_and_await_callback(path, payload, callback_action, transaction_id, message_id):
    """Sends a signed request and expects a bare ACK synchronously (the real Beckn
    shape), then polls CallbackRecord for the matching on_<action> callback that arrives
    later -- see this module's docstring and models.CallbackRecord's. Raises
    OndcRequestError on a transport failure, a non-2xx/unsigned ACK, or a callback that
    never arrives within settings.ONDC_CALLBACK_TIMEOUT_SECONDS.

    message_id (not just transaction_id+action) is what this callback is actually
    correlated by -- see models.CallbackRecord's docstring for why transaction_id+action
    alone isn't unique per call (get_status is polled repeatedly against the same
    transaction_id, a real, confirmed race otherwise)."""
    body_bytes = json.dumps(payload).encode()
    auth_header = build_authorization_header(
        body_bytes, settings.ONDC_BAP_PRIVATE_KEY, settings.ONDC_BAP_SUBSCRIBER_ID, settings.ONDC_BAP_KEY_ID,
    )
    url = f"{settings.ONDC_GATEWAY_BASE_URL}/{path}/"

    try:
        response = requests.post(
            url, data=body_bytes, headers={"Content-Type": "application/json", "Authorization": auth_header},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise OndcRequestError(f"{path}: request failed: {e}") from e

    if response.status_code != 200:
        raise OndcRequestError(f"{path}: HTTP {response.status_code}: {response.text}")

    response_auth_header = response.headers.get("Authorization", "")
    try:
        verify_authorization_header(response.content, response_auth_header, settings.ONDC_BPP_PUBLIC_KEY)
    except SignatureVerificationError as e:
        raise OndcRequestError(f"{path}: ack failed signature verification: {e}") from e

    return _await_callback(transaction_id, callback_action, message_id)


def _await_callback(transaction_id, action, message_id, timeout=None, poll_interval_seconds=0.05):
    """Polls for the on_<action> callback ondc_adapter/views.py records for THIS call
    specifically (transaction_id+action+message_id -- see models.CallbackRecord's
    docstring for why message_id, not just transaction_id+action, matters). A short poll
    interval is fine: this is an in-process DB read against Turso/SQLite, not a network
    call, and the whole point is to notice the callback almost as soon as it lands.

    A concurrent write from the callback's own request thread (see views.py's
    _record_callback) can transiently lock SQLite/Turso against this read -- caught here
    and treated the same as "not found yet," since the next poll a moment later is
    exactly the right response either way."""
    from django.db import OperationalError

    timeout = settings.ONDC_CALLBACK_TIMEOUT_SECONDS if timeout is None else timeout
    deadline = time.monotonic() + timeout
    while True:
        try:
            record = CallbackRecord.objects.filter(
                transaction_id=transaction_id, action=action, message_id=message_id, received_at__isnull=False,
            ).first()
        except OperationalError as e:
            if "locked" not in str(e):
                raise
            record = None
        if record is not None:
            return record.payload
        if time.monotonic() >= deadline:
            raise OndcRequestError(
                f"timed out after {timeout}s waiting for {action} callback "
                f"(transaction_id={transaction_id}, message_id={message_id})"
            )
        time.sleep(poll_interval_seconds)


def search(origin, destination, domain=DEFAULT_DOMAIN):
    """Returns (list of Offer, transaction_id) for one domain -- BUILD_PLAN.md Phase 1
    scope was TRV10 only; Phase 2 calls this once per domain (see search_all_domains)."""
    transaction_id = _new_transaction_id()
    message_id = uuid.uuid4().hex
    payload = {
        "context": _build_context("search", transaction_id, domain, message_id=message_id),
        "message": {"intent": {"fulfillment": {
            "start": {"location": {"descriptor": {"name": origin}}},
            "end": {"location": {"descriptor": {"name": destination}}},
        }}},
    }
    data = _post_and_await_callback("search", payload, "on_search", transaction_id, message_id)

    offers = []
    for provider in data["message"]["catalog"]["bpp/providers"]:
        for item in provider["items"]:
            fulfillment = item.get("fulfillment", {})
            offers.append(Offer(
                bpp_id=provider["id"],
                provider_name=provider["descriptor"]["name"],
                item_id=item["id"],
                item_name=item["descriptor"]["name"],
                fare=item["price"]["value"],
                eta_minutes=int(item["time"]["duration"].strip("PTM")),
                raw=item,
                domain=domain,
                transaction_id=transaction_id,
                from_place=fulfillment.get("start", {}).get("location", {}).get("descriptor", {}).get("name", origin),
                to_place=fulfillment.get("end", {}).get("location", {}).get("descriptor", {}).get("name", destination),
                mode=item.get("mode", "unknown"),
            ))
    return offers, transaction_id


def search_all_domains(origin, destination, domains=ALL_DOMAINS):
    """Fans out one signed search per domain and flattens the results into one list of
    Offer -- BUILD_PLAN.md Phase 2's multi-modal search. Each Offer already carries its
    own domain+transaction_id (see Offer's docstring), so trip_planner can select/init/
    confirm any of them independently once composed into an itinerary. A single domain
    search failing (e.g. TRV12 down) fails the whole plan loudly rather than silently
    returning a partial, misleadingly-thin set of options -- see trip_planner.services."""
    offers = []
    for domain in domains:
        domain_offers, _ = search(origin, destination, domain=domain)
        offers.extend(domain_offers)
    return offers


def select(transaction_id, bpp_id, item_id, domain=DEFAULT_DOMAIN):
    message_id = uuid.uuid4().hex
    payload = {
        "context": _build_context("select", transaction_id, domain, message_id=message_id),
        "message": {"order": {"provider": {"id": bpp_id}, "items": [{"id": item_id}]}},
    }
    return _post_and_await_callback("select", payload, "on_select", transaction_id, message_id)


def init(transaction_id, domain=DEFAULT_DOMAIN):
    message_id = uuid.uuid4().hex
    payload = {"context": _build_context("init", transaction_id, domain, message_id=message_id), "message": {}}
    return _post_and_await_callback("init", payload, "on_init", transaction_id, message_id)


def confirm(transaction_id, domain=DEFAULT_DOMAIN):
    message_id = uuid.uuid4().hex
    payload = {"context": _build_context("confirm", transaction_id, domain, message_id=message_id), "message": {}}
    data = _post_and_await_callback("confirm", payload, "on_confirm", transaction_id, message_id)
    return data["message"]["order"]["id"], data


def get_status(transaction_id, domain=DEFAULT_DOMAIN):
    # A fresh message_id on EVERY call is what makes this safe to poll repeatedly against
    # the same transaction_id (live tracking calls this over and over) -- see
    # models.CallbackRecord's docstring for the real race this closes.
    message_id = uuid.uuid4().hex
    payload = {"context": _build_context("status", transaction_id, domain, message_id=message_id), "message": {}}
    data = _post_and_await_callback("status", payload, "on_status", transaction_id, message_id)
    return data["message"]["order"]["status"], data
