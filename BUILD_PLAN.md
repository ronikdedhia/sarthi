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

## Phase 2 — Multi-mode search, single itinerary (the actual differentiator)

- [ ] Extend `ondc_adapter` to TRV11 (metro/bus) and TRV12 (intercity), reusing the Phase 1 pattern.
- [ ] Build the `trip_planner` leg-graph + multi-objective itinerary search (cost/time/transfer trade-offs) described in [ARCHITECTURE.md](./ARCHITECTURE.md).
- [ ] UI: itinerary comparison view (ranked multi-leg plans), select one, book all legs, handle partial-failure replanning.

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
