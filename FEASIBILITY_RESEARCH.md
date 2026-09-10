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
- **[opendata.ondc.org/mobility](https://opendata.ondc.org/mobility)** — a public open dataset of real ONDC mobility order data, useful for seeding realistic test scenarios or building analytics without needing live transactions at all.

**Recommended path for a resume/portfolio project**: build the entire Sarthi stack — planning engine, Django BAP protocol layer, Next.js UI — against the mock server + Pramaan first. This gets you a fully working, demoable product. Registry onboarding for real transactions becomes an optional stretch goal you pursue in parallel, not a blocker for having something to show.

## 4. Payment/settlement — a separate real-world constraint

ONDC's Payment and Settlement Protocol lets BAP/BPP pairs negotiate settlement terms directly (no single central payment gateway mandated by the network itself), but a *transacting* BAP still needs a working payment/settlement integration to actually confirm a real order (a `confirm` call generally carries payment details). For a demo, this means:
- Mocked/simulated payment confirmation is fine and sufficient against the mock server.
- A real money-moving demo would require a working payment gateway integration and, likely, a formal settlement agreement — treat this as out of scope for v1.

Source: [ONDC-Protocol-Specs — Payment and Settlement Protocol](https://github.com/ONDC-Official/ONDC-Protocol-Specs/blob/master/protocol-specifications/docs/draft/Payment%20and%20Settlement%20Protocol.md)

## 5. Turso + Django — real but non-trivial integration

Turso (built on libSQL, a SQLite fork with edge-replica support) does **not** have first-class Django support the way Postgres/MySQL/SQLite do. What exists:
- **[django-libsql](https://github.com/aaronkazah/django-libsql)** — a community Django DB backend for libSQL/Turso. Known limitation: no support for custom SQL functions, so some Django ORM features that rely on them won't work.
- **[django-pyturso](https://pypi.org/project/django-pyturso/)** — lets a Django project use its normal ORM/migrations/admin against an *embedded* local Turso database file (embedded-replica model), rather than talking to Turso's remote/edge service directly.
- **[libsql-client-py](https://github.com/tursodatabase/libsql-client-py)** — the official Python SDK, works standalone (non-ORM) against local or remote libSQL.
- SQLAlchemy has a proper libSQL dialect (`sqlalchemy-libsql`) if you decide the ORM layer should bypass Django's ORM for the parts that touch Turso.

**Practical recommendation**: don't bet the whole app's ORM on community Turso backends for a first build. Prototype the actual data access pattern early (Day 1 of the build, not late) to confirm `django-libsql` or `django-pyturso` covers what you need (migrations, JSON fields if used, transactions across the trip/booking models) — if it doesn't, the fallback is using Django's standard SQLite backend for local dev and `libsql-client-py` directly for the specific edge-sync use case, rather than forcing the whole ORM through it.
