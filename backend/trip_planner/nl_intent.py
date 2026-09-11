"""
Natural-language trip request parsing via Gemini -- lets a user type "get me from
Koramangala to T Nagar tomorrow morning, keep it cheap" instead of filling in a rigid
origin/destination form. Confirmed live 2026-09-11 against the real Gemini API
(gemini-flash-latest) using structured JSON output (responseSchema), not free-text
parsing -- reliable extraction, not regex-guessing at whatever the model feels like
returning.

This module is the ONLY place that knows Gemini exists -- everything else (views.py,
trip_planner.services.plan_itineraries) just gets back a plain
{origin, destination, cost_weight, time_weight} dict, same shape the existing /plan/
endpoint already accepts directly. Swapping the LLM provider later is a change to this
one file, not a rewrite.

Uses plain `requests` (already a project dependency) against the real REST endpoint
directly, rather than pulling in a Gemini/Google-GenAI SDK -- one fewer third-party
dependency to have compatibility surprises with, given this project's own recent history
with exactly that class of problem (see FEASIBILITY_RESEARCH.md #5).
"""
import json

import requests

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
_REQUEST_TIMEOUT_SECONDS = 15

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "origin": {"type": "STRING"},
        "destination": {"type": "STRING"},
        "cost_weight": {"type": "NUMBER"},
        "time_weight": {"type": "NUMBER"},
    },
    "required": ["origin", "destination"],
}


class NlIntentError(Exception):
    """Raised when a natural-language trip request can't be turned into
    {origin, destination, cost_weight, time_weight} -- missing API key, an unreachable
    API, a malformed response, or a response missing origin/destination."""


def _call_gemini(text, api_key):
    """Real default call_fn -- a single REST call to Gemini's generateContent endpoint
    with structured JSON output. Injected as call_fn in parse_trip_request for testing,
    so tests never make a real network call."""
    response = requests.post(
        _GEMINI_URL,
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _RESPONSE_SCHEMA,
            },
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def parse_trip_request(text, api_key=None, call_fn=None):
    """Returns {"origin": str, "destination": str, "cost_weight": float, "time_weight":
    float} extracted from a free-text trip request. cost_weight/time_weight default to
    0.5/0.5 (same defaults trip_planner.views.plan already uses) if Gemini omits them --
    the schema only requires origin/destination, since a request that doesn't express a
    cost/speed preference is common and shouldn't be treated as a parse failure.

    Raises NlIntentError (never lets a requests exception or a KeyError leak out) for:
    no API key, the call itself failing, an unparseable response, or one missing
    origin/destination.
    """
    if not api_key:
        raise NlIntentError("GEMINI_API_KEY is required for natural-language trip requests")

    call_fn = call_fn or _call_gemini
    try:
        response = call_fn(text, api_key)
    except NlIntentError:
        raise
    except Exception as e:
        raise NlIntentError(f"Gemini API unreachable or failed: {e}") from e

    try:
        raw_text = response["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise NlIntentError(f"could not parse Gemini's response as the expected JSON shape: {e}") from e

    if not parsed.get("origin"):
        raise NlIntentError("Gemini's response is missing an origin")
    if not parsed.get("destination"):
        raise NlIntentError("Gemini's response is missing a destination")

    return {
        "origin": parsed["origin"],
        "destination": parsed["destination"],
        "cost_weight": float(parsed.get("cost_weight", 0.5)),
        "time_weight": float(parsed.get("time_weight", 0.5)),
    }
