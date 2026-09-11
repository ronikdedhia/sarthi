import json

import pytest

from trip_planner.nl_intent import NlIntentError, parse_trip_request


def _fake_gemini_response(origin, destination, cost_weight=0.5, time_weight=0.5):
    """Duck-types the real Gemini generateContent response shape -- confirmed live
    2026-09-11 against the actual API with responseSchema-based structured output."""
    payload = json.dumps({
        "origin": origin, "destination": destination,
        "cost_weight": cost_weight, "time_weight": time_weight,
    })
    return {"candidates": [{"content": {"parts": [{"text": payload}]}}]}


def test_parse_trip_request_extracts_origin_and_destination(monkeypatch):
    def fake_call(text, api_key):
        assert "Koramangala" in text
        return _fake_gemini_response("Koramangala", "T Nagar", cost_weight=0.8, time_weight=0.2)

    result = parse_trip_request(
        "get me from Koramangala to T Nagar tomorrow morning, keep it cheap",
        api_key="fake-key", call_fn=fake_call,
    )

    assert result == {"origin": "Koramangala", "destination": "T Nagar", "cost_weight": 0.8, "time_weight": 0.2}


def test_parse_trip_request_defaults_weights_when_omitted(monkeypatch):
    def fake_call(text, api_key):
        return {"candidates": [{"content": {"parts": [
            {"text": json.dumps({"origin": "Koramangala", "destination": "T Nagar"})},
        ]}}]}

    result = parse_trip_request("Koramangala to T Nagar", api_key="fake-key", call_fn=fake_call)

    assert result["cost_weight"] == 0.5
    assert result["time_weight"] == 0.5


def test_parse_trip_request_raises_a_clear_error_when_api_key_missing():
    with pytest.raises(NlIntentError, match="GEMINI_API_KEY"):
        parse_trip_request("Koramangala to T Nagar", api_key=None)


def test_parse_trip_request_raises_a_clear_error_on_malformed_response():
    def fake_call(text, api_key):
        return {"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}

    with pytest.raises(NlIntentError, match="could not parse"):
        parse_trip_request("Koramangala to T Nagar", api_key="fake-key", call_fn=fake_call)


def test_parse_trip_request_raises_a_clear_error_when_origin_or_destination_missing():
    def fake_call(text, api_key):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"origin": "Koramangala"})}]}}]}

    with pytest.raises(NlIntentError, match="destination"):
        parse_trip_request("just Koramangala, no destination", api_key="fake-key", call_fn=fake_call)


def test_parse_trip_request_surfaces_call_failures(monkeypatch):
    def fake_call(text, api_key):
        raise RuntimeError("Gemini API unreachable")

    with pytest.raises(NlIntentError, match="Gemini API unreachable"):
        parse_trip_request("Koramangala to T Nagar", api_key="fake-key", call_fn=fake_call)
