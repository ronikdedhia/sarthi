# Sarthi

**Plan and book a multi-leg trip across every ONDC mobility seller at once — auto, metro, intercity bus, or flight, composed into ranked itineraries instead of five separate single-mode apps.**

Give it an origin and destination and Sarthi fans real, signed ONDC-shaped `search` calls out across all three mobility domains (ride-hailing, metro/bus, intercity), builds a leg graph out of every real offer that comes back, and ranks genuine multi-leg itineraries by cost vs. speed — e.g. an auto+metro+intercity-bus+cab route for ₹1209/~7h next to a cab+flight+cab route for ₹4549/2.5h. Book the one you want and it drives the real `select → init → confirm` sequence for every leg in order, surfacing clearly (not silently) if one leg's price or availability changed mid-booking.

## What's actually built vs. planned

This repo implements **BUILD_PLAN.md's Phase 0 through Phase 2**: multi-domain (TRV10 ride-hailing + TRV11 metro/bus + TRV12 intercity) search, a real leg-graph/multi-objective itinerary search (`trip_planner/planner.py`), and multi-leg booking with partial-failure handling — end to end and fully tested (42 backend tests). The original single-domain, single-leg flow from Phase 1 (`POST /api/trips/search/` + `/<id>/book/`) is still there, untouched, underneath the new multi-modal one. **Not yet built**: live tracking/polling of booking status pushed to the frontend, and real ONDC registry access — see [`BUILD_PLAN.md`](./BUILD_PLAN.md) Phase 3+ for that roadmap.

## Why ONDC, and the one honest simplification

ONDC's mobility domains (TRV10 ride-hailing, TRV11 metro/bus, TRV12 intercity) are real and live, and network-participant (NP) registry access requires manual approval + a registered business entity (see [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) §2) — not available for a solo project today. So `backend/mock_bpp/` is a small, self-hosted simulated multi-domain seller that speaks the *real* signed Beckn message shapes (real Ed25519 request/response signing, real search/select/init/confirm JSON structure) rather than the actual `ONDC-Official/ondc-mock-server` — see `mock_bpp/views.py`'s docstring for the full reasoning. `ondc_adapter/client.py` is the only place that knows this — everything else in the codebase just calls `search()`/`search_all_domains()`/`select()`/`init()`/`confirm()`, so pointing at a real ONDC gateway later is a config change (`ONDC_GATEWAY_BASE_URL`), not a rewrite.

## Stack

- **Backend**: Django + Django REST Framework. Four apps: `ondc_adapter` (Beckn protocol client + Ed25519 signing/verification, domain-aware across TRV10/11/12), `mock_bpp` (the simulated multi-domain seller), `trip_planner` (the leg-graph/multi-objective itinerary search — the real intellectual core), `bookings` (Trip/TripLeg/Booking/TrackingEvent models + the booking state machine, now multi-leg).
- **Database**: **Turso** (`django-pyturso`, an embedded-libSQL Django backend) — confirmed working against real migrations, UUIDField/JSONField/DecimalField models, and FK constraints (see `FEASIBILITY_RESEARCH.md` §5 for what was uncertain going in). `DJANGO_DB_ENGINE=django.db.backends.sqlite3` falls back to plain SQLite if needed.
- **Frontend**: Next.js (App Router) + Tailwind. One page: origin/destination + cheapest/balanced/fastest preference → ranked multi-leg itinerary cards → book one → per-leg confirmation status.

## Running it locally

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

This single server hosts both the real API (`/api/trips/...`) and the simulated seller (`/mock_bpp/...`) — that's why `ONDC_GATEWAY_BASE_URL` defaults to `http://localhost:8000/mock_bpp` in `sarthi_backend/settings.py`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_BASE_URL` if the backend isn't on `localhost:8000`.

### Tests

```bash
cd backend && source .venv/bin/activate
python -m pytest
```

42 tests, all passing as of this commit — signing (sign/verify round trips, tamper detection, expired windows), multi-domain search + independent per-leg select→init→confirm cycles over a real HTTP socket (`LiveServerTestCase`, not mocked), the leg-graph/multi-objective ranking logic (pure, DB-free, crafted-graph tests proving the cost/time trade-off actually holds), the booking state machine (legal/illegal transitions), multi-leg itinerary booking including a real partial-failure scenario, and the real DRF API endpoints end to end (`/api/trips/plan/`, `/api/trips/<id>/book_itinerary/`, plus the original Phase 1 endpoints).

### Try it against the demo route network

The mock catalog only knows a small fixed set of named places (not arbitrary geocoding — see `FEASIBILITY_RESEARCH.md`/`API_INTEGRATIONS.md` for why): `Koramangala`, `MG Road Metro`, `Bengaluru Bus Terminal`, `Bengaluru Airport`, `Chennai Bus Terminal`, `Chennai Central Metro`, `Chennai Airport`, `T Nagar`. `Koramangala` → `T Nagar` returns 4 ranked itineraries spanning a ₹1209/~7h auto+metro+bus+cab route to a ₹4549/2.5h cab+flight+cab route.

## Documents in this folder

| File | Contents |
|---|---|
| [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) | What's actually live on ONDC's MTT domain, and the real constraints (NP registration, signing, settlement) |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Full system design — `trip_planner`'s leg-graph search (Phase 2, built) and what's still Phase 3+ |
| [`API_INTEGRATIONS.md`](./API_INTEGRATIONS.md) | Every external API/service, what's needed, what's gated |
| [`BUILD_PLAN.md`](./BUILD_PLAN.md) | The phased roadmap — Phase 0 through Phase 2 done, Phase 3+ (live tracking, real registry) ahead |
