# Architecture & Technical Requirements

## System overview

```
┌─────────────────────┐      ┌──────────────────────────────────────┐      ┌─────────────────────────┐
│   Next.js / React    │◄────►│              Django backend           │◄────►│   Turso (libSQL) DB      │
│  - trip request UI   │ REST │  - trip planning/orchestration engine │      │  - users, trips, legs,   │
│  - itinerary view    │ /WS  │  - ONDC BAP protocol adapter           │      │    bookings, tracking    │
│  - live tracking      │      │  - signing/key management              │      │    events                │
└─────────────────────┘      │  - booking state machine                │      └─────────────────────────┘
                              └───────────────┬──────────────────────┘
                                              │ Beckn/ONDC protocol
                                              │ (search/select/init/confirm/
                                              │  status/track/update/cancel)
                                              ▼
                          ┌───────────────────────────────────────────┐
                          │   ONDC Gateway  →  BPPs per mode           │
                          │   (or, in dev: ondc-mock-server / Pramaan) │
                          │   TRV10 ride-hailing · TRV11 metro/bus ·   │
                          │   TRV12 intercity bus/flight                │
                          └───────────────────────────────────────────┘
```

## Backend — Django

Django owns three distinct responsibilities; keep them as separate apps so the ONDC protocol churn doesn't leak into planning logic:

1. **`ondc_adapter`** — the ONDC/Beckn protocol client. Handles:
   - Outbound signed `search`/`select`/`init`/`confirm`/`status`/`track`/`cancel`/`update` calls to the gateway (or mock server in dev).
   - Inbound `on_search`/`on_select`/... callback endpoints ONDC calls back into (Django REST views), with signature verification on every inbound payload.
   - Ed25519 key management — signing key + encryption key pair, `keyId` construction, request/response signing per the [signing-verification spec](https://github.com/ONDC-Official/developer-docs/blob/main/registry/signing-verification.md).
   - This app should be the **only** place that knows ONDC/Beckn exists — everything else talks to it through a clean internal interface (`search_trips(origin, destination, constraints) -> list[Offer]`), so swapping mock server for real registry later is a config change, not a rewrite.

2. **`trip_planner`** — the actual orchestration/optimization engine, and the real intellectual core of the project. **Built 2026-09-10 (BUILD_PLAN.md Phase 2):**
   - `services.plan_itineraries(origin, destination, cost_weight, time_weight)` fans out one signed `search` per domain (TRV10/11/12, via `ondc_adapter.client.search_all_domains`) and collects every returned `Offer` as a candidate leg.
   - `planner.py` (pure, DB-free — no Django/mock_bpp needed to test it) builds an undirected leg graph keyed by place name (`build_graph`), enumerates every simple path from origin to destination up to a leg cap via DFS (`find_itinerary_paths` — the demo catalog's graph is small enough that exhaustive enumeration is the right tool, not a heuristic), and ranks candidates by a weighted sum of normalized total fare and total duration (`rank_itineraries`) — `cost_weight`/`time_weight` let a caller trade cost off against speed, rather than the engine picking one fixed definition of "best." Confirmed live: Koramangala → T Nagar returns itineraries from ₹1209/417min (cost-weighted) to ₹4549/150min (time-weighted), correctly re-ranking when the weights flip.
   - Produces ranked `Itinerary` objects, each an ordered sequence of legs across independent simulated BPPs and domains (auto → metro → intercity bus → cab is one real candidate; cab → flight → cab is another).
   - On booking, `bookings.services.book_itinerary` drives each leg's `select → init → confirm` sequence in order, stopping at the first failing leg — see BUILD_PLAN.md Phase 2 for why this surfaces clearly (which legs confirmed, which failed and how, which were never attempted) rather than auto-replanning; that's real Phase 3+ scope.
   - Not yet built: constraint inputs (cost ceiling, max transfers, mode preferences, a real time window) beyond the cost/time weighting — `plan_itineraries` takes origin/destination/weights only today.

3. **`bookings`** — the persistence + state machine layer:
   - Trip, Leg, Booking, TrackingEvent models.
   - A booking state machine per leg (searched → selected → initiated → confirmed → in-progress → completed/cancelled) since ONDC's flow is asynchronous (callback-driven, not request/response in the REST sense).
   - Background workers (Celery, or Django-native async tasks) for polling `status`/`track` callbacks and pushing live updates to the frontend.

Use **Django REST Framework** for the API surface Next.js talks to; use **Django Channels** (or simple polling to start) for pushing live trip-tracking updates to the frontend without the user refreshing.

## Frontend — Next.js / React

- **Trip request flow**: single input (origin, destination, time, budget/preference sliders) → calls Django's planning endpoint → renders ranked itinerary options.
- **Itinerary view**: visualize the multi-leg plan (map + timeline), showing which BPP/mode serves each leg and live price/availability.
- **Booking flow**: confirm → per-leg booking status, with clear UI for the async nature of ONDC confirms (this isn't instant, and legs can fail independently — the UI needs to represent partial-success states honestly, not just spinner-then-done).
- **Live tracking**: once booked, poll or subscribe to leg status/location updates.
- Use Next.js API routes only as a thin proxy/BFF if you need to hide Django's internal URL or add auth-session handling; keep real logic in Django.

## Database — Turso (libSQL)

Core tables: `User`, `Trip`, `TripLeg` (mode, BPP id, origin/destination, scheduled window), `Booking` (per-leg booking state + ONDC transaction/message IDs for correlation), `TrackingEvent` (append-only log of status/track callbacks — you'll want this for debugging async ONDC flows more than for the product itself).

Given the [Turso/Django integration gaps noted in FEASIBILITY_RESEARCH.md](./FEASIBILITY_RESEARCH.md#5-turso--django--real-but-non-trivial-integration), validate early:
- Do a spike on Day 1: stand up `django-pyturso` (or `django-libsql`) with the actual model shapes above (including any JSON fields for storing raw ONDC payloads) before committing to it as the only data layer.
- Store raw ONDC request/response payloads (JSON blobs) per transaction for debugging — Beckn/ONDC flows are notoriously easier to debug by replaying logged payloads than by reasoning abstractly.

## Cross-cutting requirements

- **Idempotency**: every ONDC callback can be retried/duplicated by the network — all inbound webhook handlers must be idempotent on `transaction_id`/`message_id`.
- **Signing correctness first**: get the Ed25519 request signing and verification exactly right against the mock server before worrying about UI polish — this is the part most likely to silently break integrations.
- **Observability**: log every outbound/inbound ONDC message with correlation IDs; this protocol is async and multi-party, so "what actually happened" is usually a log-reading exercise, not something you can reproduce by clicking around.
