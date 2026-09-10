"""BUILD_PLAN.md Phase 3: "Background workers polling/subscribing to status/track
callbacks, pushed to the frontend live." This is that worker -- a real standalone
process (`python manage.py poll_bookings`), independent of any single frontend page
being open, that keeps every non-terminal Booking's status in sync with the (mock) BPP.

Why a worker AND a frontend poll (bookings.views.trip_tracking) both call
sync_booking_status/sync_trip_tracking rather than picking one: they serve different
purposes. The frontend poll updates what one open browser tab sees, on that tab's own
cadence. This worker keeps the DB itself current independent of whether anyone is
looking -- e.g. so a Telegram/email notification hook (not built here, but the natural
next step) could react to a leg going STATUS_COMPLETED without needing a browser open.
Both are safe to run at once: sync_booking_status is idempotent (a same-or-stale poll is
a no-op, see its own docstring).
"""
import logging
import time

from django.core.management.base import BaseCommand

from bookings.models import Booking
from bookings.services import sync_booking_status

logger = logging.getLogger("bookings.poll_bookings")

DEFAULT_POLL_INTERVAL_SECONDS = 3


class Command(BaseCommand):
    help = "Polls every non-terminal Booking's real status forward and applies it. Runs forever until stopped."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS,
            help=f"Seconds to sleep between poll passes (default: {DEFAULT_POLL_INTERVAL_SECONDS}).",
        )
        parser.add_argument(
            "--once", action="store_true",
            help="Run exactly one poll pass and exit, instead of looping forever -- for cron/testing.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        run_once = options["once"]

        while True:
            n = run_poll_pass()
            if n:
                self.stdout.write(f"polled {n} non-terminal booking(s)")
            if run_once:
                return
            time.sleep(interval)


def run_poll_pass():
    """One pass: sync every non-terminal Booking, return how many were checked. Split out
    from Command.handle so it's directly unit-testable without spinning up a real
    infinite loop or a subprocess."""
    terminal = (Booking.STATUS_COMPLETED, Booking.STATUS_CANCELLED, Booking.STATUS_FAILED)
    bookings = list(Booking.objects.exclude(status__in=terminal).select_related("trip_leg"))
    for booking in bookings:
        try:
            sync_booking_status(booking)
        except Exception:  # noqa: BLE001 — one booking's unexpected failure must not kill the whole poll pass
            logger.exception("poll_bookings: unexpected error syncing booking %s", booking.id)
    return len(bookings)
