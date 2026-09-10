import pytest
from django.test import TestCase

from bookings.models import Booking, Trip, TripLeg


def _make_booking():
    trip = Trip.objects.create(origin="A", destination="B")
    leg = TripLeg.objects.create(
        trip=trip, bpp_id="namma-yatri", provider_name="Namma Yatri", item_id="auto-standard",
        fare="129.00", eta_minutes=4, raw_offer={},
    )
    return Booking.objects.create(trip_leg=leg, ondc_transaction_id="txn-1")


class BookingStateMachineTests(TestCase):
    def test_the_happy_path_transition_sequence_succeeds(self):
        booking = _make_booking()

        booking.transition_to(Booking.STATUS_SELECTED)
        booking.transition_to(Booking.STATUS_INITIATED)
        booking.transition_to(Booking.STATUS_CONFIRMED)
        booking.transition_to(Booking.STATUS_IN_PROGRESS)
        booking.transition_to(Booking.STATUS_COMPLETED)

        assert Booking.objects.get(pk=booking.pk).status == Booking.STATUS_COMPLETED

    def test_skipping_a_state_is_refused(self):
        booking = _make_booking()

        with pytest.raises(Booking.InvalidTransition):
            booking.transition_to(Booking.STATUS_CONFIRMED)  # skips selected/initiated

        # the refused transition must not have partially applied
        assert Booking.objects.get(pk=booking.pk).status == Booking.STATUS_SEARCHED

    def test_a_terminal_state_accepts_no_further_transitions(self):
        booking = _make_booking()
        booking.transition_to(Booking.STATUS_FAILED)

        with pytest.raises(Booking.InvalidTransition):
            booking.transition_to(Booking.STATUS_SELECTED)

    def test_going_backwards_is_refused(self):
        booking = _make_booking()
        booking.transition_to(Booking.STATUS_SELECTED)
        booking.transition_to(Booking.STATUS_INITIATED)

        with pytest.raises(Booking.InvalidTransition):
            booking.transition_to(Booking.STATUS_SELECTED)
