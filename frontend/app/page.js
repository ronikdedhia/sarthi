"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

// BUILD_PLAN.md Phase 3: live tracking. Matches poll_bookings' own default
// DEFAULT_POLL_INTERVAL_SECONDS -- no reason for the frontend to poll faster than the
// backend worker itself advances state.
const TRACKING_POLL_INTERVAL_MS = 3000;
const TERMINAL_STATUSES = new Set(["completed", "cancelled", "failed"]);

const STATUS_STYLES = {
  confirmed: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  in_progress: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  cancelled: "bg-zinc-200 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-500",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

function StatusBadge({ status }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
        STATUS_STYLES[status] || STATUS_STYLES.confirmed
      }`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

// Live itinerary timeline -- polls GET /api/trips/<tripId>/tracking/ on an interval
// (each poll actually SYNCS every leg's Booking forward server-side, not just reads it —
// see bookings.services.sync_trip_tracking) and stops once every leg has reached a
// terminal status, so an idle tab isn't polling forever after a trip is fully done.
function TripTimeline({ tripId }) {
  const [legs, setLegs] = useState(null);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/trips/${tripId}/tracking/`);
        const body = await response.json();
        if (cancelled) return;
        if (!response.ok) {
          setError(body.error || "tracking unavailable");
          return;
        }
        setError(null);
        setLegs(body.legs);
        if (body.legs.length > 0 && body.legs.every((leg) => TERMINAL_STATUSES.has(leg.status))) {
          clearInterval(intervalRef.current);
        }
      } catch {
        if (!cancelled) setError("could not reach the Sarthi backend");
      }
    }

    poll(); // first poll immediately, don't wait a full interval to show anything
    intervalRef.current = setInterval(poll, TRACKING_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalRef.current);
    };
  }, [tripId]);

  if (error) {
    return <p className="mt-3 text-sm text-red-700 dark:text-red-300">{error}</p>;
  }
  if (!legs) {
    return <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-500">Loading live status…</p>;
  }

  return (
    <ol className="mt-3 flex flex-col gap-2 border-l-2 border-zinc-200 pl-4 dark:border-zinc-800">
      {legs.map((leg) => (
        <li key={leg.booking_id} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs font-medium uppercase text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
            {leg.mode}
          </span>
          <span className="text-zinc-700 dark:text-zinc-300">
            {leg.from_place} → {leg.to_place}
          </span>
          <span className="text-zinc-500 dark:text-zinc-500">({leg.provider_name})</span>
          <StatusBadge status={leg.status} />
        </li>
      ))}
    </ol>
  );
}

// BUILD_PLAN.md Phase 2: ranked multi-leg itinerary comparison, replacing Phase 1's
// single-domain "one search -> one bookable leg" flow (still available on the backend
// at /api/trips/search/ + /<id>/book/, untouched, for anything that still wants it).
// This page now drives /api/trips/plan/ (multi-modal leg-graph search) and
// /api/trips/<id>/book_itinerary/ (books every leg of a chosen itinerary in order).
export default function Home() {
  const [origin, setOrigin] = useState("Koramangala");
  const [destination, setDestination] = useState("T Nagar");
  const [preference, setPreference] = useState("balanced"); // "cheapest" | "balanced" | "fastest"
  const [planState, setPlanState] = useState({ status: "idle" });
  const [bookingState, setBookingState] = useState({ status: "idle" });

  const WEIGHTS = {
    cheapest: { cost_weight: 1.0, time_weight: 0.0 },
    balanced: { cost_weight: 0.5, time_weight: 0.5 },
    fastest: { cost_weight: 0.0, time_weight: 1.0 },
  };

  async function handlePlan(event) {
    event.preventDefault();
    setPlanState({ status: "loading" });
    setBookingState({ status: "idle" });
    try {
      const response = await fetch(`${API_BASE_URL}/api/trips/plan/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, destination, ...WEIGHTS[preference] }),
      });
      const body = await response.json();
      if (!response.ok) {
        setPlanState({ status: "error", message: body.error || "planning failed" });
        return;
      }
      setPlanState({ status: "success", tripId: body.trip_id, itineraries: body.itineraries });
    } catch {
      setPlanState({ status: "error", message: "could not reach the Sarthi backend — is it running on :8000?" });
    }
  }

  async function handleBook(itinerary, index) {
    setBookingState({ status: "loading", index });
    try {
      const response = await fetch(`${API_BASE_URL}/api/trips/${planState.tripId}/book_itinerary/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ legs: itinerary.legs }),
      });
      const body = await response.json();
      if (!response.ok) {
        setBookingState({ status: "error", index, message: body.error || "booking failed" });
        return;
      }
      setBookingState({ status: "success", index, result: body });
    } catch {
      setBookingState({ status: "error", index, message: "could not reach the Sarthi backend" });
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 font-sans dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">Sarthi</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Plan a trip across every ONDC mobility seller at once — auto, metro, intercity bus or flight,
          composed into ranked multi-leg itineraries — and book the one you want.
        </p>
        <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-500">
          Demo place names (the mock catalog only knows these): Koramangala, MG Road Metro, Bengaluru Bus
          Terminal, Bengaluru Airport, Chennai Bus Terminal, Chennai Central Metro, Chennai Airport, T Nagar.
        </p>

        <form onSubmit={handlePlan} className="mt-8 flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Origin
            <input
              className="rounded-md border border-zinc-300 px-3 py-2 text-black dark:border-zinc-700 dark:bg-zinc-900 dark:text-white"
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              required
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Destination
            <input
              className="rounded-md border border-zinc-300 px-3 py-2 text-black dark:border-zinc-700 dark:bg-zinc-900 dark:text-white"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              required
            />
          </label>

          <div className="flex flex-col gap-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Preference
            <div className="flex gap-2">
              {["cheapest", "balanced", "fastest"].map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setPreference(option)}
                  className={`rounded-full border px-4 py-1.5 text-sm capitalize transition-colors ${
                    preference === option
                      ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
                      : "border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          <button
            type="submit"
            className="rounded-full bg-black px-5 py-3 font-medium text-white transition-colors hover:bg-zinc-800 disabled:opacity-50 dark:bg-white dark:text-black"
            disabled={planState.status === "loading"}
          >
            {planState.status === "loading" ? "Planning…" : "Plan trip"}
          </button>
        </form>

        {planState.status === "error" && (
          <p className="mt-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {planState.message}
          </p>
        )}

        {planState.status === "success" && planState.itineraries.length === 0 && (
          <p className="mt-6 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            No route connects those two places in the demo catalog — try one of the place names listed above.
          </p>
        )}

        {planState.status === "success" && planState.itineraries.length > 0 && (
          <ul className="mt-8 flex flex-col gap-4">
            {planState.itineraries.map((itinerary, index) => (
              <li
                key={index}
                className="rounded-lg border border-zinc-200 px-4 py-4 dark:border-zinc-800"
              >
                <div className="flex items-baseline justify-between">
                  <p className="font-medium text-black dark:text-zinc-50">
                    ₹{itinerary.total_fare.toFixed(2)} · {(itinerary.total_duration_minutes / 60).toFixed(1)}h ·{" "}
                    {itinerary.leg_count} leg{itinerary.leg_count > 1 ? "s" : ""}
                  </p>
                  <button
                    onClick={() => handleBook(itinerary, index)}
                    disabled={bookingState.status === "loading"}
                    className="rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-white dark:hover:bg-zinc-900"
                  >
                    {bookingState.status === "loading" && bookingState.index === index ? "Booking…" : "Book"}
                  </button>
                </div>

                <ol className="mt-3 flex flex-col gap-2">
                  {itinerary.legs.map((leg, legIndex) => (
                    <li key={legIndex} className="flex items-center gap-3 text-sm text-zinc-600 dark:text-zinc-400">
                      <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs font-medium uppercase text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                        {leg.mode}
                      </span>
                      <span>
                        {leg.from_place} → {leg.to_place}
                      </span>
                      <span className="ml-auto">
                        {leg.provider_name} · ₹{leg.fare} · {leg.eta_minutes}m
                      </span>
                    </li>
                  ))}
                </ol>

                {bookingState.status === "error" && bookingState.index === index && (
                  <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                    {bookingState.message}
                  </p>
                )}

                {bookingState.status === "success" && bookingState.index === index && (
                  <div
                    className={`mt-3 rounded-md px-3 py-2 text-sm ${
                      bookingState.result.fully_booked
                        ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-300"
                        : "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                    }`}
                  >
                    <p className="font-medium">
                      {bookingState.result.fully_booked
                        ? "All legs confirmed — tracking live status below"
                        : `Leg ${bookingState.result.failed_leg_index + 1} failed at "${bookingState.result.failure.step}" — ${bookingState.result.bookings.length} leg(s) confirmed before it, ${bookingState.result.legs_not_attempted} never attempted`}
                    </p>

                    {bookingState.result.bookings.length > 0 && (
                      <TripTimeline tripId={bookingState.result.trip_id} />
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
