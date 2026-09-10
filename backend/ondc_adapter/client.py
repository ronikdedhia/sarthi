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


class OndcRequestError(Exception):
    """Raised for a non-2xx response, an unsigned/invalid response, or a transport
    failure -- callers should never have to distinguish those cases from a bare
    requests.RequestException, since "did the network call actually work" is the one
    question that matters here."""


@dataclasses.dataclass(frozen=True)
class Offer:
    """One bookable option from a search -- the shape trip_planner works with, so it
    never has to know Beckn's own nested provider/item/price JSON structure."""

    bpp_id: str
    provider_name: str
    item_id: str
    item_name: str
    fare: str
    eta_minutes: int
    raw: dict


def _new_transaction_id():
    return uuid.uuid4().hex


def _build_context(action, transaction_id, message_id=None):
    return {
        "domain": "ONDC:TRV10",
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


def search(origin, destination):
    """Returns a list of Offer -- BUILD_PLAN.md Phase 1 scope: TRV10 (ride-hailing) only."""
    transaction_id = _new_transaction_id()
    payload = {
        "context": _build_context("search", transaction_id),
        "message": {"intent": {"fulfillment": {
            "start": {"location": {"descriptor": {"name": origin}}},
            "end": {"location": {"descriptor": {"name": destination}}},
        }}},
    }
    data = _post("search", payload)

    offers = []
    for provider in data["message"]["catalog"]["bpp/providers"]:
        for item in provider["items"]:
            offers.append(Offer(
                bpp_id=provider["id"],
                provider_name=provider["descriptor"]["name"],
                item_id=item["id"],
                item_name=item["descriptor"]["name"],
                fare=item["price"]["value"],
                eta_minutes=int(item["time"]["duration"].strip("PTM")),
                raw=item,
            ))
    return offers, transaction_id


def select(transaction_id, bpp_id, item_id):
    payload = {
        "context": _build_context("select", transaction_id),
        "message": {"order": {"provider": {"id": bpp_id}, "items": [{"id": item_id}]}},
    }
    return _post("select", payload)


def init(transaction_id):
    payload = {"context": _build_context("init", transaction_id), "message": {}}
    return _post("init", payload)


def confirm(transaction_id):
    payload = {"context": _build_context("confirm", transaction_id), "message": {}}
    data = _post("confirm", payload)
    return data["message"]["order"]["id"], data


def get_status(transaction_id):
    payload = {"context": _build_context("status", transaction_id), "message": {}}
    data = _post("status", payload)
    return data["message"]["order"]["status"], data
