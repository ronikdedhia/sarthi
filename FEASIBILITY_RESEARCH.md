# Feasibility Research

Researched 2026-09-10. ONDC evolves its specs and network coverage frequently — re-verify domain codes and live-city coverage against the sources below before building against them, don't trust this snapshot blindly by the time you actually start.

## 1. What's actually live on ONDC's MTT domain today

- **Ride-hailing (ONDC:TRV10)** — live, spec at v2.0.1. Namma Yatri is the flagship BAP, live in ~7 cities (Bengaluru, Mysuru, Hyderabad, Kolkata, Chennai + more), entered corporate mobility via a OneBanc partnership (Jan 2026).
- **Metro / intracity bus ticketing (ONDC:TRV11)** — live, spec at v2.0.0. As of June 2026, metro ticketing is live across Bengaluru, Chennai, Delhi, Kochi, Pune, Nagpur, and all three Mumbai Metro lines. Network-wide claims ~300,000 daily bus/metro bookings.
- **Intercity bus + airline ticketing (ONDC:TRV12)** — live per the official mobility-specification repo.
- **Hotel booking / heritage-site entry passes** — referenced in ONDC's own domain literature as part of the Travel vertical (possibly under a later TRV code, e.g. TRV13/TRV14) but I could not confirm a live, transacting BAP/BPP pair in this sub-domain as of this research pass — **treat as not yet reliably live, verify before depending on it for a v1 demo.**
- Kochi Metro, and 30+ apps overall (Uber, Rapido, Paytm, ixigo, Namma Yatri among them) transact tickets through the network per Business Standard reporting.

**Implication for Sarthi**: a realistic v1 scope is auto/cab (TRV10) + metro/bus (TRV11) + intercity bus/flight (TRV12) multi-leg composition. Don't promise hotel-leg booking in a v1 demo unless you've personally confirmed a live BPP for it.

Sources:
- [ONDC-Official/mobility-specification](https://github.com/ONDC-Official/mobility-specification)
- [ONDC Mobility Services Developer Guide](https://ondc-official.github.io/mobility-specification/)
- [Govt-backed ONDC enables over 300,000 daily bus, metro ticket bookings — Business Standard](https://www.business-standard.com/industry/news/ondc-enables-three-lakh-daily-bus-and-metro-ticket-bookings-126060101212_1.html)
- [Namma Yatri enters corporate mobility with OneBanc — AngelOne](https://www.angelone.in/news/unlisted-companies/bengaluru-based-namma-yatri-enters-corporate-mobility-with-onebanc-partnership)
- [Yatri Sathi — Wikipedia](https://en.wikipedia.org/wiki/Yatri_Sathi)

## 2. The hard constraint: becoming a Network Participant (NP) is not developer self-serve

To transact on the real ONDC network (even staging) as a Buyer App, you must:
1. Register in the **ONDC registry** with a Subscriber ID, and hold a **valid FQDN/DNS domain + SSL certificate** — the domain literally becomes part of your subscriber identity.
2. Generate a **self-signed digital certificate** with separate Ed25519 key pairs for signing and encryption, and every request/callback must be cryptographically signed and verified (Blake2b hashing, `keyId` format `{subscriber_id}|{unique_key_id}|ed25519`).
3. Get your Staging → Pre-Production → Production subscriber_id **approved by ONDC's registrar** via the Network Participant Portal — this is a manual approval workflow, not instant self-serve signup.

The public documentation does not describe an exemption for individual/hobby developers — the process is written for registered business entities. This is the single biggest feasibility risk for Sarthi as a solo project: **you may not get a fast, self-serve path onto the real staging registry.**

Sources:
- [ONDC-Official/developer-docs — Onboarding of Participants](https://github.com/ONDC-Official/developer-docs/blob/main/registry/Onboarding%20of%20Participants.md)
- [ONDC-Official/developer-docs — signing-verification.md](https://github.com/ONDC-Official/developer-docs/blob/main/registry/signing-verification.md)

## 3. The workaround: build and demo against ONDC's own mock/test tooling first

ONDC publishes tooling specifically meant to let you build and validate protocol compliance **without** a live registry entry:
- **[ONDC-Official/ondc-mock-server](https://github.com/ONDC-Official/ondc-mock-server)** — a mock BPP/gateway you can point your BAP at locally, for exercising the full search → select → init → confirm → status → track → cancel flow without touching the real network.
- **[ONDC-Official/beckn-sandbox-api](https://github.com/ONDC-Official/beckn-sandbox-api)** — sandbox API tooling for the underlying Beckn protocol.
- **[Pramaan](https://pramaan.ondc.org/)** ([repo](https://github.com/ONDC-Official/pramaan)) — ONDC's own certification/integration test bench, explicitly built to "democratize access to ONDC" for testing/validation across staging, pre-prod, and production-shaped scenarios, including the TRV10/TRV11/TRV12 flows specifically.
- ~~**opendata.ondc.org/mobility** — a public open dataset of real ONDC mobility order data~~ — **checked 2026-09-10, a dead end**: the subdomain doesn't resolve at all (confirmed not a general network issue — `ondc.org`/`www.ondc.org` resolve fine from the same environment). Don't plan around this as a real data source without independently re-verifying it first.

**Recommended path for a resume/portfolio project**: build the entire Sarthi stack — planning engine, Django BAP protocol layer, Next.js UI — against the mock server + Pramaan first. This gets you a fully working, demoable product. Registry onboarding for real transactions becomes an optional stretch goal you pursue in parallel, not a blocker for having something to show.

## 4. Payment/settlement — a separate real-world constraint

ONDC's Payment and Settlement Protocol lets BAP/BPP pairs negotiate settlement terms directly (no single central payment gateway mandated by the network itself), but a *transacting* BAP still needs a working payment/settlement integration to actually confirm a real order (a `confirm` call generally carries payment details). For a demo, this means:
- Mocked/simulated payment confirmation is fine and sufficient against the mock server.
- A real money-moving demo would require a working payment gateway integration and, likely, a formal settlement agreement — treat this as out of scope for v1.

Source: [ONDC-Protocol-Specs — Payment and Settlement Protocol](https://github.com/ONDC-Official/ONDC-Protocol-Specs/blob/master/protocol-specifications/docs/draft/Payment%20and%20Settlement%20Protocol.md)

## 5. Turso + Django — tried three ways, abandoned; real Postgres (Supabase) instead

**2026-09-11 update: Turso's Django story turned out not to work in practice, on real
testing against a real hosted database — not just the theoretical gaps described below.**
Three separate approaches were tried, in this order:

1. **`django_pyturso`** (embedded local-file libSQL) — confirmed working for local
   migrations/UUID/JSONField/DecimalField/FK constraints, but its local file lives on
   Render free tier's *ephemeral* disk (wiped on every spin-down/redeploy), so it can't
   hold real data in production at all. Also depends on a package called `turso` (not
   `libsql`) that is embedded-file-only by design — confirmed via direct testing: it
   raises `turso.IoError: open: NotFound` against a real `libsql://` URL, and
   `django_pyturso`'s own connection code explicitly rejects URL-shaped `NAME` values and
   never passes an auth token through. Also requires Python ≥3.14.
2. **[django-libsql](https://github.com/aaronkazah/django-libsql)** (ENGINE
   `libsql.db.backends.sqlite3`, remote mode) — depends on `libsql_client`, whose DB-API2
   shim fails to import at all on Python 3.14 (`ImportError: cannot import name 'version'
   from 'sqlite3.dbapi2'` — an already-latest-release upstream bug, no fix available).
   Even on Python 3.12 (sidestepping that), its WebSocket/Hrana transport got a real `400
   Invalid response status` connecting to the actual hosted database, with no working
   plain-HTTP fallback registered in that same compatibility layer (`KeyError: 'https'`).
3. **A custom Django backend built directly on `libsql`** (a third, distinct package from
   both above) — this one genuinely connects: a real `SELECT 1` against the real database
   succeeded with `libsql.connect(database=url, auth_token=token)`. But wiring it into
   Django (subclassing the stock sqlite3 backend, since `libsql` is meant to be
   DB-API-compatible) hit three separate, real incompatibilities in a row: a flat
   exception hierarchy missing `DataError`/`IntegrityError`/etc. that Django's error
   wrapper expects to exist unconditionally; a read-only `Connection.isolation_level`
   where Django's autocommit toggle expects to set it (libsql exposes a separate,
   writable `.autocommit` boolean instead — the newer Python 3.12+ sqlite3 API style, not
   the older one Django's stock backend still uses); and a `cursor()` that rejects the
   `factory=` kwarg Django passes. Each was fixed individually, but the *pattern* — a new,
   different incompatibility every time the last one was cleared, with `migrate` not even
   as far as schema/introspection code yet — was the signal to stop patching and switch
   approaches rather than keep guessing how many more there were.

**What actually shipped**: real Postgres via Supabase, using Django's own first-party
`django.db.backends.postgresql` backend (wired through `dj-database-url` for connection-
string parsing). Confirmed live: real migrations against the actual hosted database (every
one of Sarthi's real models, UUID/JSONField/DecimalField/FK constraints included, applied
clean) and a real ORM create → read → delete round trip. Zero exotic-driver risk left —
this is the most battle-tested database backend Django has.

**Practical recommendation for a future project**: don't bet a Django app's ORM on
community Turso backends, even after confirming the underlying database connects fine
standalone — the Django integration layer is where the real risk lives, and it's deep
enough that "prototype it on Day 1" (this doc's own earlier advice) can still cost you a
full pivot later. If Turso's specific edge/embedded-replica properties aren't a hard
requirement, real Postgres (Supabase, Neon, Render's own, etc.) removes this entire class
of risk from the start.
