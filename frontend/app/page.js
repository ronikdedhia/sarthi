"use client";

import { useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

// Phase 1 scope (see ../BUILD_PLAN.md): one search -> one bookable leg. The Phase 2
// multi-leg itinerary comparison view this will grow into isn't built yet -- this page
// intentionally stays a single search-and-book flow rather than stubbing UI for a
// planner that doesn't exist on the backend yet.
export default function Home() {
  const [origin, setOrigin] = useState("Koramangala");
  const [destination, setDestination] = useState("Chennai Airport");
  const [searchState, setSearchState] = useState({ status: "idle" });
  const [bookingState, setBookingState] = useState({ status: "idle" });

  async function handleSearch(event) {
    event.preventDefault();
    setSearchState({ status: "loading" });
    setBookingState({ status: "idle" });
    try {
      const response = await fetch(`${API_BASE_URL}/api/trips/search/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origin, destination }),
      });
      const body = await response.json();
      if (!response.ok) {
        setSearchState({ status: "error", message: body.error || "search failed" });
        return;
      }
      setSearchState({ status: "success", tripId: body.trip_id, transactionId: body.transaction_id, offers: body.offers });
    } catch {
      setSearchState({ status: "error", message: "could not reach the Sarthi backend — is it running on :8000?" });
    }
  }

  async function handleBook(offer) {
    setBookingState({ status: "loading", offer });
    try {
      const response = await fetch(`${API_BASE_URL}/api/trips/${searchState.tripId}/book/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transaction_id: searchState.transactionId, ...offer }),
      });
      const body = await response.json();
      if (!response.ok) {
        setBookingState({ status: "error", message: body.error || "booking failed", step: body.step });
        return;
      }
      setBookingState({ status: "success", bookingId: body.booking_id, orderStatus: body.status, orderId: body.order_id });
    } catch {
      setBookingState({ status: "error", message: "could not reach the Sarthi backend" });
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 font-sans dark:bg-black">
      <main className="mx-auto max-w-xl px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">Sarthi</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Search a ride across every ONDC ride-hailing seller at once, and book the one you want.
        </p>

        <form onSubmit={handleSearch} className="mt-8 flex flex-col gap-4">
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
          <button
            type="submit"
            className="rounded-full bg-black px-5 py-3 font-medium text-white transition-colors hover:bg-zinc-800 disabled:opacity-50 dark:bg-white dark:text-black"
            disabled={searchState.status === "loading"}
          >
            {searchState.status === "loading" ? "Searching…" : "Search rides"}
          </button>
        </form>

        {searchState.status === "error" && (
          <p className="mt-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {searchState.message}
          </p>
        )}

        {searchState.status === "success" && (
          <ul className="mt-8 flex flex-col gap-3">
            {searchState.offers.map((offer) => (
              <li
                key={`${offer.bpp_id}-${offer.item_id}`}
                className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800"
              >
                <div>
                  <p className="font-medium text-black dark:text-zinc-50">
                    {offer.provider_name} — {offer.item_name}
                  </p>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    ₹{offer.fare} · {offer.eta_minutes} min away
                  </p>
                </div>
                <button
                  onClick={() => handleBook(offer)}
                  disabled={bookingState.status === "loading"}
                  className="rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-white dark:hover:bg-zinc-900"
                >
                  {bookingState.status === "loading" && bookingState.offer?.item_id === offer.item_id ? "Booking…" : "Book"}
                </button>
              </li>
            ))}
          </ul>
        )}

        {bookingState.status === "error" && (
          <p className="mt-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            Booking failed at step &ldquo;{bookingState.step}&rdquo;: {bookingState.message}
          </p>
        )}

        {bookingState.status === "success" && (
          <div className="mt-6 rounded-md bg-green-50 px-4 py-3 text-sm text-green-800 dark:bg-green-950 dark:text-green-300">
            <p className="font-medium">Booking {bookingState.orderStatus}</p>
            <p>Order ID: {bookingState.orderId}</p>
          </div>
        )}
      </main>
    </div>
  );
}
