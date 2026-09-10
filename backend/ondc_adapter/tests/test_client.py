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
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

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


class MultiDomainSearchTests(LiveServerTestCase):
    """BUILD_PLAN.md Phase 2: TRV11 (metro/bus) and TRV12 (intercity) alongside TRV10."""

    def _gateway_url_override(self):
        return override_settings(
            ONDC_GATEWAY_BASE_URL=f"{self.live_server_url}/mock_bpp", SARTHI_BASE_URL=self.live_server_url,
        )

    def test_trv11_search_returns_metro_offers_with_place_and_mode(self):
        with self._gateway_url_override():
            offers, transaction_id = client.search("MG Road Metro", "Bengaluru Bus Terminal", domain="ONDC:TRV11")

        assert transaction_id
        assert {o.bpp_id for o in offers} == {"namma-metro", "chennai-metro"}
        namma_metro = next(o for o in offers if o.bpp_id == "namma-metro")
        assert namma_metro.mode == "metro"
        assert namma_metro.from_place == "MG Road Metro"
        assert namma_metro.to_place == "Bengaluru Bus Terminal"
        assert namma_metro.domain == "ONDC:TRV11"
        assert namma_metro.transaction_id == transaction_id

    def test_trv12_search_returns_intercity_offers(self):
        with self._gateway_url_override():
            offers, _ = client.search("Bengaluru Bus Terminal", "Chennai Bus Terminal", domain="ONDC:TRV12")

        assert {o.bpp_id for o in offers} == {"intrcity-smartbus", "indigo"}
        flight = next(o for o in offers if o.bpp_id == "indigo")
        assert flight.mode == "flight"
        assert flight.eta_minutes == 75

    def test_search_all_domains_flattens_offers_from_all_three_domains_with_distinct_transaction_ids(self):
        with self._gateway_url_override():
            offers = client.search_all_domains("Koramangala", "T Nagar")

        domains_seen = {o.domain for o in offers}
        assert domains_seen == {"ONDC:TRV10", "ONDC:TRV11", "ONDC:TRV12"}
        # each domain's search is a SEPARATE signed call -> a separate transaction_id,
        # carried per-offer so a later leg can be selected/confirmed independently
        txn_ids_by_domain = {o.domain: o.transaction_id for o in offers}
        assert len(set(txn_ids_by_domain.values())) == 3

    def test_a_leg_from_one_domain_can_be_selected_initiated_and_confirmed_using_its_own_transaction_id(self):
        """Proves an individual Offer returned by search_all_domains is independently
        bookable via its own domain+transaction_id -- exactly what a multi-leg itinerary
        booking flow (bookings.services.book_itinerary) relies on."""
        with self._gateway_url_override():
            offers = client.search_all_domains("Koramangala", "T Nagar")
            metro_leg = next(o for o in offers if o.domain == "ONDC:TRV11" and o.bpp_id == "namma-metro")

            client.select(metro_leg.transaction_id, metro_leg.bpp_id, metro_leg.item_id, domain=metro_leg.domain)
            client.init(metro_leg.transaction_id, domain=metro_leg.domain)
            order_id, confirm_data = client.confirm(metro_leg.transaction_id, domain=metro_leg.domain)

        assert order_id.startswith("order-")
        assert confirm_data["message"]["order"]["status"] == "confirmed"


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
