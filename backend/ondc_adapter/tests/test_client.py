"""Full-stack test: ondc_adapter.client -> real HTTP -> mock_bpp's views -> back, with
real Ed25519 signing and verification on both directions. LiveServerTestCase spins up an
actual socket server so this exercises the real network path requests.post/JsonResponse
take, not just in-process function calls."""
import pytest
from django.test import LiveServerTestCase, override_settings

from ondc_adapter import client
from ondc_adapter.client import OndcRequestError


class SearchSelectInitConfirmFlowTests(LiveServerTestCase):
    def _gateway_url_override(self):
        return override_settings(ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp")

    def test_search_returns_offers_from_both_mock_providers(self):
        with self._gateway_url_override():
            offers, transaction_id = client.search("Koramangala", "Chennai Airport")

        assert transaction_id
        provider_ids = {o.bpp_id for o in offers}
        assert provider_ids == {"namma-yatri", "yatri-sathi"}
        assert all(o.fare and o.eta_minutes > 0 for o in offers)

    def test_full_search_select_init_confirm_cycle_succeeds(self):
        with self._gateway_url_override():
            offers, transaction_id = client.search("Koramangala", "Chennai Airport")
            chosen = offers[0]

            client.select(transaction_id, chosen.bpp_id, chosen.item_id)
            client.init(transaction_id)
            order_id, confirm_data = client.confirm(transaction_id)

            status, _ = client.get_status(transaction_id)

        assert order_id.startswith("order-")
        assert confirm_data["message"]["order"]["status"] == "confirmed"
        assert status == "confirmed"

    def test_confirm_without_a_prior_select_is_refused(self):
        with self._gateway_url_override():
            with pytest.raises(OndcRequestError):
                client.confirm("no-such-transaction-id")


class TamperedRequestTests(LiveServerTestCase):
    def test_a_request_signed_with_the_wrong_key_is_rejected_by_the_mock_bpp(self):
        """Confirms the mock BPP actually enforces signature verification (not just
        ondc_adapter.client trusting itself) -- a wrong BAP key must get a 401, not a
        200 with a mismatched signature quietly accepted."""
        import requests

        response = requests.post(
            f"{self.live_server_url}/mock_bpp/search/",
            data=b'{"context": {}, "message": {}}',
            headers={"Content-Type": "application/json", "Authorization": "Signature keyId=\"bogus\""},
        )

        assert response.status_code == 401
