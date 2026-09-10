# Build Plan

Phased so you always have something demoable, and so the ONDC registry-approval uncertainty (see [FEASIBILITY_RESEARCH.md §2](./FEASIBILITY_RESEARCH.md#2-the-hard-constraint-becoming-a-network-participant-np-is-not-developer-self-serve)) never blocks progress.

## Phase 0 — Foundations & spikes (get the risky unknowns out of the way first)

- [ ] Django project skeleton with `ondc_adapter`, `trip_planner`, `bookings` apps; Next.js project skeleton.
- [ ] **Turso spike**: stand up `django-pyturso` (or `django-libsql`) against your real `Trip`/`TripLeg`/`Booking` model shapes, including any JSON payload fields. Confirm migrations, transactions, and querying all work before building anything on top. If it doesn't hold up, fall back to Django's SQLite backend locally + `libsql-client-py` directly for the specific sync use case.
- [ ] **ONDC mock server spike**: get [ondc-mock-server](https://github.com/ONDC-Official/ondc-mock-server) running locally, and get one full `search → on_search` round trip working from Django with correct Ed25519 request signing. This is the highest-risk integration piece — de-risk it before building the planner on top of an untested adapter.
- [ ] Pick and stand up the OSM stack (Nominatim + OSRM) or Google Maps keys for geocoding/transfer-time estimation.

## Phase 1 — Single-mode, single-leg booking (prove the adapter end-to-end)

- [ ] `ondc_adapter`: full `search/select/init/confirm/status/track/cancel` cycle against the mock server for **one** domain only (TRV10 ride-hailing).
- [ ] Minimal Next.js UI: enter origin/destination, see ride options, book one, see status update.
- [ ] Get the async callback handling and idempotency right here — this is the pattern every other mode reuses.

## Phase 2 — Multi-mode search, single itinerary (the actual differentiator) — ✅ done 2026-09-10

- [x] Extended `ondc_adapter` to TRV11 (metro/bus) and TRV12 (intercity) — every function (`search`/`select`/`init`/`confirm`/`get_status`) takes an optional `domain` (default TRV10, so Phase 1 call sites/tests are untouched). `search_all_domains(origin, destination)` fans out one signed search per domain and flattens the results; each returned `Offer` carries its own `domain`+`transaction_id`, so any leg is independently select/init/confirm-able regardless of which other domain's search it came from.
- [x] `mock_bpp`'s catalog is now route-based across all three domains — a small fixed set of named places (Koramangala, MG Road Metro, Bengaluru Bus Terminal, Bengaluru Airport, Chennai Bus Terminal, Chennai Central Metro, Chennai Airport, T Nagar) connected by real (simulated) TRV10/TRV11/TRV12 routes, giving trip_planner real edges to compose multi-leg itineraries across independent sellers from.
- [x] Built `trip_planner/planner.py` — the actual leg-graph + multi-objective search: `build_graph` (undirected adjacency list over candidate legs), `find_itinerary_paths` (DFS enumeration of every simple path up to a leg cap — the graph is small enough that exhaustive enumeration is correct, not a heuristic), `rank_itineraries` (weighted-sum scoring over normalized total fare + total duration, so callers can trade cost off against speed via `cost_weight`/`time_weight`). Pure, DB-free, unit-tested with crafted graphs proving the cost/time trade-off actually holds (`trip_planner/tests/test_planner.py`) — confirmed live too: Koramangala → T Nagar returns 4 ranked itineraries spanning ₹1209/417min (auto+metro+bus+cab, cost-weighted top pick) to ₹4549/150min (cab+flight+cab, time-weighted top pick).
- [x] New endpoint `POST /api/trips/plan/` (multi-modal search, returns ranked itineraries) alongside the untouched Phase 1 `POST /api/trips/search/`. New `bookings.services.book_itinerary` books every leg of a chosen itinerary in order via the existing `book_leg`, stopping at the first failing leg and returning a result that shows exactly what confirmed, what failed and why, and what was never attempted (`POST /api/trips/<id>/book_itinerary/`) — see the next bullet for why this surfaces rather than auto-replans.
- [x] UI: the Next.js page now shows ranked multi-leg itinerary cards (fare/duration/leg count, per-leg mode/place/provider), a cheapest/balanced/fastest preference toggle, book-the-whole-itinerary, and a clear partial-booking status view (which legs confirmed, which one failed and at what step, how many were never attempted).
- [~] **Partial-failure handling is "surface clearly," not "replan"** — ARCHITECTURE.md's original phrasing offered either. Automatic re-planning around a failed leg (re-querying `trip_planner` for a fresh route from the failed leg's origin) is real, scoped-out work for Phase 3+, not silently half-built here — `bookings.services.book_itinerary`'s docstring says so explicitly. Tested live: a leg with a since-invalidated `item_id` fails cleanly at the `select` step, its own Booking persists as `STATUS_FAILED`, and every earlier leg's confirmed booking is untouched.

42 backend tests passing as of this phase (up from 17 at the end of Phase 1).

## Phase 3 — Live tracking & polish

- [ ] Background workers polling/subscribing to `status`/`track` callbacks, pushed to the frontend live.
- [ ] Itinerary timeline/map visualization.
- [ ] Seed realistic demo data from [opendata.ondc.org/mobility](https://opendata.ondc.org/mobility) so the demo doesn't feel synthetic.

## Phase 4 — Stretch: real network access

- [ ] Apply for ONDC staging registry access in parallel with Phases 1–3 (manual approval process, start it early since it's out of your control).
- [ ] If/when approved: swap the mock-server config for the real staging gateway — this should be a config change only if `ondc_adapter`'s internal interface was kept clean, per the architecture doc's isolation principle.
- [ ] Do **not** treat this phase as required for the project to be "done" — a fully working mock-server-backed demo with a real optimization engine is already a complete, demoable, resume-worthy project on its own.

## What "done" looks like for a resume/portfolio pass

A live demo where: you type a multi-city, multi-modal trip request → Sarthi shows 2-3 ranked itinerary options spanning auto + metro + intercity bus/flight from *different, independent* ONDC seller apps → you book one → you watch live status updates as each leg progresses → if a leg's price/availability changes mid-booking, the system replans rather than failing silently. That's the whole pitch, and none of it requires real registry access to prove.
