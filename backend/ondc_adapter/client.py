"""The ONE place the rest of Sarthi talks to ONDC/Beckn through -- ARCHITECTURE.md's
isolation principle: "everything else talks to it through a clean internal interface
... so swapping mock server for real registry later is a config change, not a rewrite."

Today ONDC_GATEWAY_BASE_URL points at this same repo's mock_bpp app (see
FEASIBILITY_RESEARCH.md #2-3 for why: real registry/NP approval is a manual process this
project doesn't have yet). Every call is still really signed and really verified against
the mock BPP's response signature -- nothing here is faked at the protocol level, only
the network topology (one simulated seller instead of a gateway fanning out to many)
is simplified for local dev.
"""
import dataclasses
import json
import uuid
from datetime import datetime, timezone

import requests
from django.conf import settings

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
        "bpp_id": settings.ONDC_BPP_SUBSCRIBER_ID,
        "transaction_id": transaction_id,
        "message_id": message_id or uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _post(path, payload):
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
        raise OndcRequestError(f"{path}: response failed signature verification: {e}") from e

    return response.json()


def search(origin, destination, domain=DEFAULT_DOMAIN):
    """Returns (list of Offer, transaction_id) for one domain -- BUILD_PLAN.md Phase 1
    scope was TRV10 only; Phase 2 calls this once per domain (see search_all_domains)."""
    transaction_id = _new_transaction_id()
    payload = {
        "context": _build_context("search", transaction_id, domain),
        "message": {"intent": {"fulfillment": {
            "start": {"location": {"descriptor": {"name": origin}}},
            "end": {"location": {"descriptor": {"name": destination}}},
        }}},
    }
    data = _post("search", payload)

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
    payload = {
        "context": _build_context("select", transaction_id, domain),
        "message": {"order": {"provider": {"id": bpp_id}, "items": [{"id": item_id}]}},
    }
    return _post("select", payload)


def init(transaction_id, domain=DEFAULT_DOMAIN):
    payload = {"context": _build_context("init", transaction_id, domain), "message": {}}
    return _post("init", payload)


def confirm(transaction_id, domain=DEFAULT_DOMAIN):
    payload = {"context": _build_context("confirm", transaction_id, domain), "message": {}}
    data = _post("confirm", payload)
    return data["message"]["order"]["id"], data


def get_status(transaction_id, domain=DEFAULT_DOMAIN):
    payload = {"context": _build_context("status", transaction_id, domain), "message": {}}
    data = _post("status", payload)
    return data["message"]["order"]["status"], data
