"""BUILD_PLAN.md Phase 4 readiness: proves the protocol is now GENUINELY async, not just
that client.py's external behavior didn't regress (test_client.py already covers that).
Real HTTP round trip via LiveServerTestCase -- mock_bpp really ACKs, then really calls
back later to ondc_adapter's real on_* endpoints."""
import json
import time

import pytest
import requests
from django.test import LiveServerTestCase, override_settings

from ondc_adapter import client
from ondc_adapter.client import OndcRequestError
from ondc_adapter.models import CallbackRecord
from ondc_adapter.signing import build_authorization_header


class MockBppAsyncBehaviorTests(LiveServerTestCase):
    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_search_response_is_a_bare_ack_not_the_real_catalog(self):
        """The synchronous simplification this replaced returned the full catalog in the
        same HTTP response -- a real BPP/gateway never does that. Confirms mock_bpp's
        immediate response is genuinely just an ACK."""
        from django.conf import settings

        with self._gateway_url_override():
            transaction_id = "test-txn-ack-shape"
            message_id = "test-msg-ack-shape"
            context = {
                "domain": "ONDC:TRV10", "action": "search", "bap_id": settings.ONDC_BAP_SUBSCRIBER_ID,
                "bap_uri": f"{settings.SARTHI_BASE_URL}/ondc_adapter", "bpp_id": settings.ONDC_BPP_SUBSCRIBER_ID,
                "transaction_id": transaction_id, "message_id": message_id, "timestamp": "2026-09-10T00:00:00Z",
            }
            payload = {"context": context, "message": {"intent": {"fulfillment": {
                "start": {"location": {"descriptor": {"name": "Koramangala"}}},
                "end": {"location": {"descriptor": {"name": "Chennai Airport"}}},
            }}}}
            body_bytes = json.dumps(payload).encode()
            auth_header = build_authorization_header(
                body_bytes, settings.ONDC_BAP_PRIVATE_KEY, settings.ONDC_BAP_SUBSCRIBER_ID, settings.ONDC_BAP_KEY_ID,
            )
            response = requests.post(
                f"{self.live_server_url}/mock_bpp/search/", data=body_bytes,
                headers={"Content-Type": "application/json", "Authorization": auth_header}, timeout=10,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == {"ack": {"status": "ACK"}}
        assert "catalog" not in body["message"]

    def test_the_real_catalog_arrives_later_via_a_genuine_on_search_callback(self):
        """Directly inspects CallbackRecord to prove the real payload was delivered by a
        SEPARATE POST after the ACK, not smuggled into the ACK response somehow."""
        with self._gateway_url_override():
            offers, transaction_id = client.search("Koramangala", "Chennai Airport")

        assert len(offers) >= 1
        record = CallbackRecord.objects.get(transaction_id=transaction_id, action="on_search")
        assert record.received_at is not None
        assert "catalog" in record.payload["message"]


class RepeatedStatusPollRaceRegressionTests(LiveServerTestCase):
    """Regression test for a real race found and fixed 2026-09-10: CallbackRecord used to
    be keyed by (transaction_id, action) alone. get_status() reuses the SAME transaction_id
    across repeated polls (exactly what live tracking does), so a second poll could match
    the STALE CallbackRecord from the first poll before the new callback for the SECOND
    call had even arrived -- silently returning old data instead of the real current
    status. Fixed by correlating on (transaction_id, action, message_id), a fresh
    message_id generated per call."""

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    @override_settings(MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS=1, MOCK_ORDER_COMPLETED_AFTER_SECONDS=1,
                        MOCK_BPP_CALLBACK_DELAY_SECONDS=0.02)
    def test_a_second_status_poll_reflects_new_elapsed_time_not_the_first_polls_cached_value(self):
        with self._gateway_url_override():
            offers, transaction_id = client.search("Koramangala", "Chennai Airport")
            offer = offers[0]
            client.select(transaction_id, offer.bpp_id, offer.item_id)
            client.init(transaction_id)
            client.confirm(transaction_id)

            first_status, _ = client.get_status(transaction_id)
            assert first_status == "confirmed"  # too soon to have advanced

            time.sleep(1.2)
            second_status, _ = client.get_status(transaction_id)

        assert second_status == "in_progress"  # this exact assertion failed before the fix

    def test_two_distinct_calls_never_collide_on_a_stale_record_even_without_a_real_status_change(self):
        """Simpler variant that doesn't depend on mock_bpp's elapsed-time simulation --
        two get_status() calls back to back must each wait for and return THEIR OWN
        callback, not silently short-circuit on whatever the previous call already wrote."""
        with self._gateway_url_override():
            offers, transaction_id = client.search("Koramangala", "Chennai Airport")
            offer = offers[0]
            client.select(transaction_id, offer.bpp_id, offer.item_id)
            client.init(transaction_id)
            client.confirm(transaction_id)

            status_a, _ = client.get_status(transaction_id)
            status_b, _ = client.get_status(transaction_id)

        assert status_a == status_b == "confirmed"
        # two SEPARATE CallbackRecord rows, one per call -- not one row overwritten in a
        # way that could have raced
        records = CallbackRecord.objects.filter(transaction_id=transaction_id, action="on_status")
        assert records.count() == 2
        assert len({r.message_id for r in records}) == 2


class UnreachableCallbackTests(LiveServerTestCase):
    def test_an_unreachable_bap_uri_times_out_cleanly_rather_than_hanging_forever(self):
        """SARTHI_BASE_URL left at its default (a real port, but not this test server's
        actual dynamic one) -- mock_bpp's callback POST to it can never succeed. Proves
        the poll loop fails loudly and promptly (ONDC_CALLBACK_TIMEOUT_SECONDS) rather
        than hanging indefinitely when a real gateway's own callback delivery fails."""
        with override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", ONDC_CALLBACK_TIMEOUT_SECONDS=0.3,
        ):
            with pytest.raises(OndcRequestError, match="timed out"):
                client.search("Koramangala", "Chennai Airport")
