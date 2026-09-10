# Phase 4 Registration Guide — real ONDC Network Participant access

For when you (not this code) have what's needed below. Written 2026-09-10, alongside the
codebase readiness work described in `BUILD_PLAN.md`'s Phase 4 section — read that first
for what's already ready vs. what a real registration would still change.

## 1. What business entity actually qualifies

**A sole proprietorship with a valid GST registration is sufficient** — you do not need
an LLP or a private limited company to register as an ONDC Network Participant. Confirmed
against ONDC's own current seller-onboarding guidance (2026): businesses/sellers need a
valid GSTIN + PAN, and a sole proprietorship with GST is explicitly enough for someone
testing on the network, not just larger sellers. A Pvt Ltd is only *recommended* if you
plan to scale commercially or raise funding — not a requirement for this project's scope
(a buyer/BAP app, not even a seller).

Concretely, before applying:
- [ ] Register a sole proprietorship (or any of: partnership, LLP, Pvt Ltd) in your name —
  a sole proprietorship is the fastest path for an individual.
- [ ] Get a GSTIN for that entity (mandatory for e-commerce participation regardless of
  turnover, per Section 24 of the CGST Act).
- [ ] A bank account in the entity's name for settlement — a sole proprietor can use a
  savings account in their own name if it matches the PAN the business is registered
  under; you don't strictly need a separate current account to start.

## 2. Domain + SSL

- [ ] A real domain name you control (e.g. `sarthi.yourdomain.com`) — this becomes part of
  your ONDC subscriber ID and is where a real gateway/BPP sends your `on_search`/
  `on_select`/`on_init`/`on_confirm`/`on_status` callbacks (see `ondc_adapter/views.py`,
  built 2026-09-10 — this is the part of the codebase that's actually ready for this).
- [ ] A valid SSL certificate for that domain (Let's Encrypt is fine — ONDC doesn't
  mandate a specific CA).
- [ ] The domain must be **publicly reachable** — a real gateway calling back to
  `localhost` (this project's dev default) obviously can't work; you'd deploy this
  Django app somewhere with a public IP/domain and set `SARTHI_BASE_URL` to the real
  `https://` URL there.

## 3. Ed25519 keys

Already solved by this codebase — `ondc_adapter/signing.py`'s `generate_signing_keypair()`
generates a real Ed25519 keypair. For real registry use:
- [ ] Generate a FRESH keypair (don't reuse the demo one committed nowhere — see
  `sarthi_backend/settings.py`'s `ONDC_BAP_PRIVATE_KEY`/`ONDC_BAP_PUBLIC_KEY` env vars).
- [ ] Register the **public** key with the ONDC registry as part of subscription (below);
  keep the private key exactly as secret as `NUVAMA_API_SECRET` was treated in the
  sibling `tick-trade` project — env var only, never committed.

## 4. The actual registration process

- [ ] Go to the **ONDC Network Participant Portal** (the same portal referenced in
  `FEASIBILITY_RESEARCH.md` §2 — search "ONDC network participant registration portal";
  the exact URL has changed before, don't hardcode an old one here).
- [ ] Submit: Subscriber ID (built from your domain), your public key, Country, City/
  Cities you'll operate in, and Type = **buyer app (BAP)** — Sarthi is a buyer app, not a
  seller, so you're registering as a BAP, not a seller/BPP.
- [ ] ONDC's registrar reviews and approves manually — no published fixed SLA in their
  public docs as of this writing; treat it as taking real time (days to weeks), not
  instant. Start this in parallel with other work, not as a blocker.
- [ ] Once approved, you get Staging → Pre-Production → Production subscriber_id
  approval in that order (see `FEASIBILITY_RESEARCH.md` §2) — staging first, always.

## 5. What changes in THIS codebase once you have real access

Genuinely just config, now that the Phase 4 readiness work is done:
- `ONDC_GATEWAY_BASE_URL` → the real ONDC staging gateway's URL (not `.../mock_bpp`).
- `SARTHI_BASE_URL` → your real, public `https://` domain.
- `ONDC_BAP_SUBSCRIBER_ID`/`ONDC_BAP_KEY_ID`/`ONDC_BAP_PRIVATE_KEY`/`ONDC_BAP_PUBLIC_KEY` →
  your real registered identity and keys (not the demo `sarthi.example.bap` ones).
- You'd stop needing `mock_bpp` and `ONDC_BPP_*` settings entirely for search/select/
  init/confirm — those only exist to simulate a seller locally.

What would **still** need real-world validation, not just config:
- The real gateway's actual `on_search`/etc. callback payload shape may not byte-for-byte
  match `mock_bpp`'s simulation — `ondc_adapter/client.py`'s parsing (`data["message"]
  ["catalog"]["bpp/providers"]` etc.) is written to the public Beckn spec, but has only
  ever been exercised against this project's own simulator, never a real BPP. Budget a
  real smoke test before trusting it, same posture the sibling `tick-trade` project takes
  toward its own broker SDK.
- Payment/settlement (`FEASIBILITY_RESEARCH.md` §4) is still explicitly out of scope.

## Sources for the business-entity claim (checked 2026-09-10, don't treat as permanently
current — re-verify before actually registering)
- ONDC seller-onboarding guidance confirming sole proprietorship + GST is sufficient to
  register, with Pvt Ltd only recommended for scaling, not required to start.
