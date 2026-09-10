"""BUILD_PLAN.md Phase 3: a confirmed mock order's status now progresses with elapsed real
time (confirmed -> in_progress -> completed) instead of sitting at "confirmed" forever --
these are pure, deterministic tests using an injected `now`, not real sleeps."""
from datetime import datetime, timedelta

from django.test import TestCase, override_settings

from mock_bpp import store


@override_settings(MOCK_ORDER_IN_PROGRESS_AFTER_SECONDS=10, MOCK_ORDER_COMPLETED_AFTER_SECONDS=20)
class OrderStatusProgressionTests(TestCase):
    def setUp(self):
        self.confirmed_at = datetime(2026, 9, 10, 12, 0, 0)
        store.remember_selection("txn-1", "ONDC:TRV10", "namma-yatri", "auto-standard")
        store.mark_initiated("txn-1")
        store.confirm_order("txn-1", "order-abc123", now=self.confirmed_at)

    def test_status_is_confirmed_immediately_after_confirming(self):
        order = store.get_order("txn-1", now=self.confirmed_at)
        assert order["status"] == "confirmed"

    def test_status_is_still_confirmed_just_before_the_in_progress_threshold(self):
        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=9))
        assert order["status"] == "confirmed"

    def test_status_advances_to_in_progress_at_the_threshold(self):
        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=10))
        assert order["status"] == "in_progress"

    def test_status_stays_in_progress_before_the_completed_threshold(self):
        # completed_after = in_progress_after (10) + completed_after (20) = 30s total
        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=29))
        assert order["status"] == "in_progress"

    def test_status_advances_to_completed_at_the_threshold(self):
        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=30))
        assert order["status"] == "completed"

    def test_status_stays_completed_long_after_the_threshold(self):
        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(hours=5))
        assert order["status"] == "completed"

    def test_get_order_does_not_mutate_the_underlying_stored_state(self):
        """Each call recomputes from the stored confirmed_at -- calling get_order with a
        later `now` must not permanently advance the order, e.g. a poll from a stale
        client clock must not corrupt what a later, correctly-timed poll reports."""
        store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=30))  # "completed"

        order = store.get_order("txn-1", now=self.confirmed_at + timedelta(seconds=1))
        assert order["status"] == "confirmed"


class NonConfirmedOrderStatusTests(TestCase):
    def test_a_selected_but_not_yet_confirmed_order_reports_its_raw_status_unaffected_by_time(self):
        store.remember_selection("txn-2", "ONDC:TRV10", "namma-yatri", "auto-standard")

        order = store.get_order("txn-2", now=datetime(2030, 1, 1))

        assert order["status"] == "selected"

    def test_an_unknown_transaction_returns_none(self):
        assert store.get_order("no-such-transaction") is None
