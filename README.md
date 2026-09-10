# Sarthi

**Search and book a ride across every ONDC ride-hailing seller in one place — the MVP slice of an eventual multi-modal (auto → metro → intercity) trip planner.**

Give it an origin and destination and Sarthi fans a real, signed ONDC-shaped `search` out to every ride-hailing seller on the network, shows you every offer side by side, and drives the real `select → init → confirm` sequence when you book one — instead of you checking Namma Yatri, Yatri Sathi, and every other single-mode app separately.

## What's actually built vs. planned

This repo currently implements **BUILD_PLAN.md's Phase 0 + Phase 1 only**: single-domain (ONDC:TRV10 ride-hailing), single-leg search and booking, end to end and fully tested. It does **not** yet do Phase 2's multi-modal itinerary composition (metro/intercity legs, multi-objective route optimization) — see [`BUILD_PLAN.md`](./BUILD_PLAN.md) for that roadmap. Don't expect multi-leg trips yet; this is the proven vertical slice everything else builds on.

## Why ONDC, and the one honest simplification

ONDC's ride-hailing domain (TRV10) is real, live, and network-participant (NP) registry access requires manual approval + a registered business entity (see [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) §2) — not available for a solo project today. So `backend/mock_bpp/` is a small, self-hosted simulated ride-hailing seller that speaks the *real* signed Beckn message shapes (real Ed25519 request/response signing, real search/select/init/confirm JSON structure) rather than the actual `ONDC-Official/ondc-mock-server` — see `mock_bpp/views.py`'s docstring for the full reasoning. `ondc_adapter/client.py` is the only place that knows this — everything else in the codebase just calls `search()`/`select()`/`init()`/`confirm()`, so pointing at a real ONDC gateway later is a config change (`ONDC_GATEWAY_BASE_URL`), not a rewrite.

## Stack

- **Backend**: Django + Django REST Framework. Three apps: `ondc_adapter` (Beckn protocol client + Ed25519 signing/verification), `mock_bpp` (the simulated seller), `bookings` (Trip/TripLeg/Booking/TrackingEvent models + the booking state machine).
- **Database**: **Turso** (`django-pyturso`, an embedded-libSQL Django backend) — confirmed working against real migrations, UUIDField/JSONField/DecimalField models, and FK constraints (see `FEASIBILITY_RESEARCH.md` §5 for what was uncertain going in). `DJANGO_DB_ENGINE=django.db.backends.sqlite3` falls back to plain SQLite if needed.
- **Frontend**: Next.js (App Router) + Tailwind. One page: search form → offer list → book.

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

17 tests, all passing as of this commit — signing (sign/verify round trips, tamper detection, expired windows), the full search→select→init→confirm→status cycle over a real HTTP socket (`LiveServerTestCase`, not mocked), the booking state machine (legal/illegal transitions), and the real DRF API endpoints end to end.

## Documents in this folder

| File | Contents |
|---|---|
| [`FEASIBILITY_RESEARCH.md`](./FEASIBILITY_RESEARCH.md) | What's actually live on ONDC's MTT domain, and the real constraints (NP registration, signing, settlement) |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Full system design, including Phase 2+ (multi-modal) not yet built |
| [`API_INTEGRATIONS.md`](./API_INTEGRATIONS.md) | Every external API/service, what's needed, what's gated |
| [`BUILD_PLAN.md`](./BUILD_PLAN.md) | The phased roadmap this MVP is Phase 0+1 of |
