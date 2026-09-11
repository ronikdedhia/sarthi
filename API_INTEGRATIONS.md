# API & Service Integrations

Every external dependency Sarthi needs, why, and how hard it is to get access.

## 1. ONDC / Beckn protocol (core dependency)

| What | Why | Access difficulty |
|---|---|---|
| **ONDC Registry** (subscriber lookup/onboarding) | Required to be a real Network Participant and discover BPPs on the network | **Hard** — needs FQDN+SSL, Ed25519 keypair, manual registrar approval. See [FEASIBILITY_RESEARCH.md §2](./FEASIBILITY_RESEARCH.md#2-the-hard-constraint-becoming-a-network-participant-np-is-not-developer-self-serve) |
| **ONDC Gateway** (routes `search` broadcasts to relevant BPPs) | The entry point for discovering ride/metro/bus/flight options across sellers | Same registry gating as above |
| **Mobility domain APIs — TRV10 (ride-hailing), TRV11 (metro/intracity bus), TRV12 (intercity bus/flight)** | The actual `search/select/init/confirm/status/track/update/cancel` transaction flow per mode | Spec is fully public: [ONDC-Official/mobility-specification](https://github.com/ONDC-Official/mobility-specification) |
| **ONDC mock server** | Build/test the full protocol flow with zero registry approval needed | Public, no approval needed: [ondc-mock-server](https://github.com/ONDC-Official/ondc-mock-server) |
| **Pramaan test bench** | ONDC's own certification/integration tool, covers TRV10/11/12 flows explicitly | Public: [pramaan.ondc.org](https://pramaan.ondc.org/), [repo](https://github.com/ONDC-Official/pramaan) |
| **opendata.ondc.org/mobility** | Hoped to be a real public dataset for seeding realistic demo scenarios | **Dead end, checked 2026-09-10**: the subdomain does not resolve at all (confirmed not a general network issue — `ondc.org`/`www.ondc.org` resolve fine from the same environment). Not usable; the hand-built demo route catalog was kept as-is rather than replaced with something that only *looks* more "real." |

**Build order**: mock server + Pramaan first (zero-approval, fully public) → apply for staging registry access in parallel as a stretch goal, not a blocker.

## 2. Signing / cryptography

- **Ed25519 signing** — every ONDC request/callback must be signed and verified (Blake2b payload hashing). This isn't a third-party API, it's a library-level requirement (`PyNaCl` or similar in Python) implemented inside the `ondc_adapter` Django app per the [signing-verification spec](https://github.com/ONDC-Official/developer-docs/blob/main/registry/signing-verification.md).
- No external account needed for dev/mock-server work; only needed for real registry registration (self-signed cert + keypair you generate yourself).

## 3. Maps / geocoding / routing (supplementary — ONDC doesn't provide this)

ONDC's `search` gives you candidate legs from BPPs, but it does **not** give you geocoding (turning "Koramangala" into coordinates) or walking/transfer-time estimation between legs (e.g., time to walk from a bus stop to a metro entrance). You need a separate mapping API for:
- Geocoding free-text origin/destination into coordinates.
- Estimating transfer walk-time/distance between two leg endpoints, to know if a proposed itinerary is actually physically feasible.

Options: Google Maps Platform (Directions/Distance Matrix/Geocoding APIs — paid, but has a free tier sufficient for a demo), or OpenStreetMap-based alternatives (Nominatim for geocoding, OSRM for routing — free, self-hostable, no API key management, good fit for a resume project since it avoids a billing dependency).

**Recommendation**: start with OSM/Nominatim/OSRM for the demo to avoid Google API billing/key friction; note in your writeup that swapping to Google Maps is a one-line config change if higher accuracy is needed later.

## 4. Payments (only needed if you go beyond mocked confirms)

ONDC's Payment and Settlement Protocol lets BAP/BPP negotiate settlement bilaterally rather than mandating one gateway — see [FEASIBILITY_RESEARCH.md §4](./FEASIBILITY_RESEARCH.md#4-paymentsettlement--a-separate-real-world-constraint). For v1, mock the payment confirmation step entirely. If you later want a real-money demo, a UPI-based gateway (Razorpay, Cashfree, or Setu) would be the integration point — treat this as an explicit stretch goal, not part of the core build.

## 5. Database — Postgres (Supabase)

Not a third-party "API" in the traditional sense but worth listing here since it's an external managed service: [Supabase](https://supabase.com) (real Postgres). Free tier is sufficient for a portfolio project (500MB DB, 1GB storage, 5GB egress — commercial use explicitly allowed; the one caveat is a free project pauses after 7 days of zero database activity, though data isn't lost, just needs resuming). Turso was tried first and abandoned after three separate real, blocking integration failures — see [FEASIBILITY_RESEARCH.md §5](./FEASIBILITY_RESEARCH.md#5-turso--django--tried-three-ways-abandoned-real-postgres-supabase-instead) for the full story.

## 6. Natural-language trip requests — Gemini

[Google AI Studio](https://aistudio.google.com) — free API key, no card required. Used by `trip_planner/nl_intent.py` for `POST /api/trips/plan_from_text/` only; the original form-based `/plan/` needs nothing here. Free tier (confirmed 2026-09) is Flash-only (Gemini 2.5 Pro moved behind billing) — 250 req/day on Flash, 1,000 req/day on Flash-Lite — comfortably enough for a portfolio demo at one request per trip search. One real caveat confirmed live: `gemini-flash-latest` occasionally returns a transient `503`; Sarthi surfaces this as a clear `422` to the caller rather than retrying silently or crashing. Structured JSON output (`responseSchema`) is used for extraction, not free-text parsing — reliable, not a guess at whatever the model feels like returning.

## 7. Auth (your own users, not ONDC)

Sarthi needs its own end-user auth (people planning trips) — this is unrelated to ONDC's NP-to-NP signing. Standard Django auth + DRF token/JWT (e.g. `djangorestframework-simplejwt`) is sufficient; no external identity provider is required unless you want social login for demo polish.

## Summary: what's blocked vs. buildable today

| Dependency | Buildable today, no approval needed |
|---|---|
| Mobility protocol flow (mock server + Pramaan) | ✅ Yes |
| Trip planning/optimization engine | ✅ Yes — pure logic, no external dependency |
| Django + Next.js + Postgres (Supabase) stack | ✅ Yes |
| Geocoding/routing (OSM stack) | ✅ Yes |
| Natural-language trip requests (Gemini) | ✅ Yes — free API key, confirmed live |
| Real ONDC registry transactions | ⚠️ Gated on NP registration/approval — pursue in parallel, don't block v1 on it |
| Real payment settlement | ⚠️ Out of scope for v1, mock it |
