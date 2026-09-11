# Sarthi

**Plan and book a multi-leg trip across every ONDC mobility seller at once — auto, metro, intercity bus, or flight, composed into ranked itineraries instead of five separate single-mode apps.**

Give it an origin and destination — or just type "get me from Koramangala to T Nagar tomorrow morning, keep it cheap" and let Gemini turn that into a real search — and Sarthi fans real, signed ONDC-shaped `search` calls out across all three mobility domains (ride-hailing, metro/bus, intercity), builds a leg graph out of every real offer that comes back, and ranks genuine multi-leg itineraries by cost vs. speed — e.g. an auto+metro+intercity-bus+cab route for ₹1209/~7h next to a cab+flight+cab route for ₹4549/2.5h. Book the one you want and it drives the real `select → init → confirm` sequence for every leg in order, surfacing clearly (not silently) if one leg's price or availability changed mid-booking — then watch every leg's status genuinely progress (`confirmed → in_progress → completed`) live, both in the UI and via a background worker that keeps the trip's real state current whether or not anyone's watching.

## What's actually built vs. planned

This repo implements **BUILD_PLAN.md's Phase 0 through Phase 3, plus Phase 4's codebase-readiness work**: multi-domain (TRV10 ride-hailing + TRV11 metro/bus + TRV12 intercity) search, a real leg-graph/multi-objective itinerary search (`trip_planner/planner.py`), multi-leg booking with partial-failure handling, live per-leg status tracking backed by a real background worker, a genuinely **asynchronous** Beckn protocol implementation (real `on_search`/`on_select`/`on_init`/`on_confirm`/`on_status` callback endpoints, not a same-response simplification), and a **natural-language trip request** front door (`POST /api/trips/plan_from_text/`, Gemini structured-JSON extraction feeding the exact same planner) — end to end and fully tested (74 backend tests). The original single-domain, single-leg flow from Phase 1 (`POST /api/trips/search/` + `/<id>/book/`) is still there, untouched, underneath the new multi-modal one. **Not done**: actual ONDC registry registration — it needs a real business entity + domain, neither of which existed as of this pass. See [`PHASE4_REGISTRATION_GUIDE.md`](./PHASE4_REGISTRATION_GUIDE.md) for exactly what that takes (a sole proprietorship with GST is enough — no need for an LLP/Pvt Ltd) and [`BUILD_PLAN.md`](./BUILD_PLAN.md) Phase 4 for what readiness work is already done vs. still gated on that. One honest dead end along the way: [opendata.ondc.org/mobility](https://opendata.ondc.org/mobility), hoped to seed more realistic demo data, doesn't resolve at all — see `BUILD_PLAN.md`'s Phase 3 notes.

## Why ONDC, and the one honest simplification

ONDC's mobility domains (TRV10 ride-hailing, TRV11 metro/bus, TRV12 intercity) are real and live, and network-participant (NP) registry access requires manual approval + a registered business entity (see [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) §2, and [`PHASE4_REGISTRATION_GUIDE.md`](./PHASE4_REGISTRATION_GUIDE.md) for exactly what's needed) — not available for a solo project today. So `backend/mock_bpp/` is a small, self-hosted simulated multi-domain seller that speaks the *real* signed, **asynchronous** Beckn message shapes (real Ed25519 request/response signing; a real ACK-then-callback round trip, not the same-response simplification this project shipped with initially — see `BUILD_PLAN.md`'s Phase 4 notes for what changed and why) rather than the actual `ONDC-Official/ondc-mock-server`. `ondc_adapter/client.py` is the only place that knows any of this exists — everything else in the codebase just calls `search()`/`search_all_domains()`/`select()`/`init()`/`confirm()`, so pointing at a real ONDC gateway later really is just `ONDC_GATEWAY_BASE_URL` + `SARTHI_BASE_URL` config now, not a rewrite — that claim didn't hold before the Phase 4 readiness work and does now.

## Stack

- **Backend**: Django + Django REST Framework. Four apps: `ondc_adapter` (Beckn protocol client + Ed25519 signing/verification, domain-aware across TRV10/11/12), `mock_bpp` (the simulated multi-domain seller, whose confirmed orders now genuinely progress `confirmed → in_progress → completed` over real elapsed time), `trip_planner` (the leg-graph/multi-objective itinerary search — the real intellectual core — plus `nl_intent.py`, a real Gemini structured-JSON extraction layer turning a free-text request into the same `{origin, destination, cost_weight, time_weight}` shape the form-based endpoint already takes), `bookings` (Trip/TripLeg/Booking/TrackingEvent models + the booking state machine, now multi-leg, plus `sync_booking_status`/`sync_trip_tracking` which pull the BPP's real current status and advance Sarthi's own DB to match).
- **Background worker**: `python manage.py poll_bookings` (`--interval`/`--once`) — polls every non-terminal booking on its own cadence, independent of any open browser tab, so a trip's tracked state stays current even with nobody watching.
- **Database**: **Postgres (Supabase)** — Django's own first-party `django.db.backends.postgresql` backend via `dj-database-url`. Confirmed live: real migrations (UUID/JSONField/DecimalField models, FK constraints) and a real ORM write/read/delete round trip against the actual hosted database. Turso was tried three separate ways first (`django-libsql`, `django_pyturso`, a custom `libsql`-based backend) — all three hit real, blocking compatibility problems on actual testing; see `FEASIBILITY_RESEARCH.md` §5 for the full story. Falls back to plain local SQLite if `DATABASE_URL` isn't set (local dev only — tests always use SQLite regardless).
- **Frontend**: Next.js (App Router) + Tailwind. One page: origin/destination + cheapest/balanced/fastest preference → ranked multi-leg itinerary cards → book one → a live, auto-polling per-leg timeline (mode, places, provider, color-coded status) that stops polling once every leg reaches a terminal state.

## Running it locally

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

This single server hosts the real API (`/api/trips/...`), the simulated seller (`/mock_bpp/...`), *and* the real inbound Beckn callback endpoints (`/ondc_adapter/on_search/` etc.) — that's why `ONDC_GATEWAY_BASE_URL` and `SARTHI_BASE_URL` both default to `localhost:8000` in `sarthi_backend/settings.py`: the mock seller calls back to this same process.

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

74 tests, all passing as of this commit — signing (sign/verify round trips, tamper detection, expired windows), multi-domain search + independent per-leg select→init→confirm cycles over a real HTTP socket (`LiveServerTestCase`, not mocked), the leg-graph/multi-objective ranking logic (pure, DB-free, crafted-graph tests proving the cost/time trade-off actually holds), the booking state machine (legal/illegal transitions), multi-leg itinerary booking including a real partial-failure scenario, the real DRF API endpoints end to end (`/api/trips/plan/`, `/api/trips/plan_from_text/`, `/api/trips/<id>/book_itinerary/`, `/api/trips/<id>/tracking/`, plus the original Phase 1 endpoints), the real async callback protocol itself (`ondc_adapter/tests/test_callbacks.py`: a bare ACK response, a real separate callback POST, and a regression test for a real race a repeated status poll used to hit), and Gemini extraction (`trip_planner/tests/test_nl_intent.py`, a fake `call_fn` injected so tests never make a real network call — the real Gemini integration was separately confirmed live: a real natural-language request through the running dev server correctly extracted origin/destination/weights and returned real ranked itineraries end to end). Several tests prove genuine status progression over *real* elapsed time through the real HTTP stack (`override_settings` + `time.sleep()` across real polls), not a mocked single-state check.

### Try it against the demo route network

The mock catalog only knows a small fixed set of named places (not arbitrary geocoding — see `FEASIBILITY_RESEARCH.md`/`API_INTEGRATIONS.md` for why): `Koramangala`, `MG Road Metro`, `Bengaluru Bus Terminal`, `Bengaluru Airport`, `Chennai Bus Terminal`, `Chennai Central Metro`, `Chennai Airport`, `T Nagar`. `Koramangala` → `T Nagar` returns 4 ranked itineraries spanning a ₹1209/~7h auto+metro+bus+cab route to a ₹4549/2.5h cab+flight+cab route.

## Documents in this folder

| File | Contents |
|---|---|
| [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) | What's actually live on ONDC's MTT domain, and the real constraints (NP registration, signing, settlement) |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Full system design — `trip_planner`'s leg-graph search, the live-tracking pipeline, and the real async callback protocol (all built) |
| [`API_INTEGRATIONS.md`](./API_INTEGRATIONS.md) | Every external API/service, what's needed, what's gated |
| [`BUILD_PLAN.md`](./BUILD_PLAN.md) | The phased roadmap — Phase 0 through Phase 3 done, Phase 4's codebase readiness done, actual registration still ahead |
| [`PHASE4_REGISTRATION_GUIDE.md`](./PHASE4_REGISTRATION_GUIDE.md) | Concrete, verified steps for real ONDC registration once you have a business entity + domain |
