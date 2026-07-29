# Platform Security & Event Contracts — Program Status

**This file is the tracked, versioned status of the Foundation program.**
`.superpowers/sdd/progress.md` is gitignored scratch and must never again be the only
record of a decision or a debt. Anything that survives a fresh clone lives here.

Last updated: 2026-07-29
Branch: `codex/integration-bachelor-hardening`
Plan: `docs/superpowers/plans/2026-07-23-platform-security-event-contracts-foundation.md`
Spec: `docs/superpowers/specs/2026-07-23-platform-security-event-contracts-design.md`

---

## 1. Task state

| Task | Title | State |
|------|-------|-------|
| 1 | Secure settings and auth value types | done |
| 2 | HMAC signing and v2 envelopes | done |
| 3 | Central n8n workflow registry | done |
| 4 | TypeScript n8n signature nodes | done |
| 5 | Odoo session, throttle and ACL models | done |
| 6 | Backend session stack | done |
| 7 | Grace-mode gates | done |
| 8 | Atomic Odoo jobs, outbox, receipts, leases | done, defects open (R2) |
| 9 | Backend-to-n8n event transport | done, defects open (R2) |
| 10 | Signed v2 routes | done |
| 11 | Job-bound media and artifact contracts | done, defects open (R1/R2) |
| 12 | Odoo-19 core idempotency handoff | **blocked** — no `codex/odoo19-cutover`, no cutover plan, so no `wave1-odoo19-handoff` tag |
| 13 | Postgres role separation | **statically complete, live acceptance open** (R4) |
| 14 | n8n credential management | done, defects open (R3) |
| 15 | Custom n8n image, network boundaries, Caddy, TLS | **blocked** by 12; scope amended, see §3 |
| 16 | Production route surface and browser idempotency | **blocked** — plan L7999 declares it consumes Task 12 and Task 15 |
| 17 | Two-database, concurrency, restart, rollout gates | blocked by everything above |

**Correction of record:** an earlier ledger entry claimed Task 16 was startable next. It is not.
The plan's own Interfaces block for Task 16 reads
`Consumes: authenticated principal Task 7, scoped reservation Task 12, production network Task 15.`

## 2. Sequencing

```
R1 Backend ─┐
R2 Odoo ────┼─> whole-branch gate ─> Odoo-19 handoff ─> 12 ─> 15 ─> 16 ─> 17
R3 n8n ─────┤
R4 DB/Plan ─┘
```

R1, R2 and R3 are independent remediation lanes and may run in parallel worktrees, each with its
own adversarial review gate. R4 is serial and gated on the Odoo-19 handoff for its second half.
No Foundation task numbered 12 or higher starts before the whole-branch gate is green again.

## 3. Frozen decisions

These are decisions, not proposals. Changing one requires editing this file in a commit.

1. **The backend-to-n8n transport is AT-LEAST-ONCE and stays that way.** No amount of backend or
   Odoo work makes it exactly-once. A crash after n8n performs a side effect but before
   `api_ack_delivery` commits causes lease expiry and a second delivery carrying a *fresh* nonce
   and signature, so signature-level replay defence cannot catch it by construction.

2. **Exactly-once is a property of each external effect, never of the transport.** Every external
   effect carries the stable key `pwr:{event_id}:{payload_fingerprint}:{effect_kind}`. Where the
   provider supports idempotency keys, that string is the key. Where the provider supports neither
   an idempotency key nor a status query, the system **cannot** promise exactly-once for that
   effect; it must reconcile afterwards or mark the job `review_required`. Task 15's original
   "deduplicate `event_id` + fingerprint before the workflow" is REJECTED: after a lease expires,
   the spec deliberately allows a new generation carrying the same event id and an identical body
   as a legitimate retry, so a durable pre-workflow marker would block exactly the retry the
   design depends on.

3. **`queued -> retry_scheduled` is a recovery-only edge.** It is legal only together with a
   generation increment, lease clearing and an outbox requeue, applied atomically. The general
   `_transition()` must not accept it as a bare edge. This supersedes the unsigned-off plan
   amendment made during Task 8.

4. **The Odoo-18 port is a narrow, formally approved auth-compatibility port — or it is deleted.**
   `odoo/addons18/picking_assistant_integration` may contain session, auth and throttle only. It
   must carry its own test module. "Keep both addons in sync" is withdrawn as guidance: full
   parity would itself violate the spec, which forbids a Foundation copy under `addons18`. A
   parity matrix listing exactly which models are ported and which are deliberately absent lives
   in that addon's README.

5. **The X-Forwarded-For "overwrite" debt is struck.** `header_up +X-Forwarded-For ...` appends,
   it does not overwrite, so the recorded remedy never matched the recorded intent. Caddy already
   ignores client-supplied `X-Forwarded-*` from untrusted peers by default. The real obligations
   that replace it: pin the Caddy image to an explicit version, and set `trusted_proxies`
   explicitly rather than relying on a default of an unpinned image. Owner: Task 15.

6. **Task 13 is "statically complete, live acceptance open".** No script has run against a real
   PostgreSQL cluster. It closes only after one successful clone → apply → verify → demote →
   rollback run against a disposable instance.

7. **Task 16 stays blocked until 12 and 15 are complete.** Its CSRF, Origin and idempotency gate
   is app-inclusion-level and owns no router body; the plan's ownership note forbids editing
   `backend/app/routers/cluster.py` and `voice.py` inside it.

8. **The request body limit is a Task 15 obligation and needs two layers.** `await request.body()`
   necessarily precedes signature verification, and `Content-Length` is bypassable with chunked
   encoding. Caddy's `request_body max_size` protects the edge only and requires Caddy >= 2.10,
   which is a second reason to pin the image. Direct n8n → backend calls need an ASGI-level
   streaming limit as well.

## 4. Debt register

Findings from the whole-branch adversarial review of 2026-07-29
(`.superpowers/sdd/codex-wholebranch-review.md`, base `foundation-plan-approved-2026-07-23`,
head `1e240f5`). "Verified" means read in the code by a second reviewer, not merely reported.

| # | Finding | Severity | Owner | Verified |
|---|---------|----------|-------|----------|
| 1 | `runtime_profile` is a bare `str`; any value except exactly `production` selects the full development posture, and `mobile_header_grace_mode` defaults to `True` | Critical | R1 | yes — `config.py` |
| 2a | `main.py` CORS uses unvalidated `cors_origins` while `validate_runtime_security` validates `pwa_origins`; `allow_credentials=True` | Critical | R1 | yes — `main.py:101`, `config.py:178` |
| 2b | No CSRF/Origin gate on browser mutations; all three `cluster.py` mutations use `get_required_picker_identity`, and `require_browser_csrf` is defined but wired to no router | Critical | Task 16 | yes — `dependencies.py:348`, `routers/cluster.py` |
| 3 | The v2 workflow verifier proves neither the exact acceptance target nor a `process == true` gate dominating every effect | Critical | R3 | yes — `workflow_verifier.py:1031` |
| 4 | Task 15's event-dedup design cannot deliver the claimed exactly-once effect | Critical (plan) | §3.2 | n/a — design |
| 5 | `api_apply_callback` checks state, token and generation but not `processing_lease_expires_at`, while its sibling `api_accept_event` does | Important | R2 | yes — `receipts.py:388` vs `:232` |
| 6 | Inverted lock order: acceptance locks the job then reserves the nonce; callback reserves the nonce then locks the job | Important | R2 | yes — `receipts.py:167` vs `:348` |
| 7 | `api_requeue_dead` searches and writes without `FOR UPDATE` or post-lock revalidation, and accepts archived/share supervisors | Important | R2 | yes — `outbox.py:172` |
| 8 | All five legacy n8n callbacks build their workflow service from a browser/grace dependency, so they 401 in production before the handler runs | Important | R1 | yes — `dependencies.py:280` |
| 9a | PDF validation budgets stream objects but not inline images in the content stream | Important | R1 | partially — `binary_validation.py:391` |
| 9b | The Odoo-side PDF check is a raw byte denylist that name-escaping defeats | Important | R1 | yes — `resources.py:469` |
| 10 | Login throttling checks, then authenticates, then records — parallel requests all pass before the first failure is booked | Important | R2 | yes — `auth_sessions.py:146` |
| 11 | Retention deletes delivered/dead outbox rows regardless of job state; the watchdog then tolerates a missing outbox | Important | R2 | no |
| 12 | The registry accepts any generation string and the verifier skips everything except exactly `v2` | Important | R3 | yes — `workflow_registry.py:120`, `verify-workflows.py:49` |
| 13 | The importer emits `"credential"` (one object); `stage_workflow.py` reads `"credentials"` (a list) — every real binding resolves to zero candidates | Important | R3 | yes — `import-workflows.sh:341` vs `stage_workflow.py:227` |
| 14 | Compose mounts only `init-n8n-db.sql`, which requires the `n8n_app` role that the unmounted `init-db-roles.sh` would create, and runs against `POSTGRES_DB=postgres` | Important | R4 | yes — `docker-compose.yml:31` |
| 15 | The migration does not meet its own reversibility contract: existing roles unhardened, compose checked by global grep, demotion immediately after a stub-satisfiable verifier | Important | R4 | no |
| 16 | Credential file permissions are checked on host paths and read from container paths; the Node side checks neither mode, owner, symlink nor regular-file | Important | R3 | no |
| M1 | `session.py:111` can return a concurrently revoked or expired session once more during role marking | Minor | R2 | no |
| M2 | The nonce GC deletes at most 1000 rows per ten minutes and reports no remainder | Minor | R2 | no |
| M3 | Product images are anonymous and instance-selectable under the default-on development grace | Minor | R1 (closed by #1) | yes |

### Raised during remediation (2026-07-29)

- **#5b — resource routes bind to a lease, not to a token.** Closing finding #5 routed
  `resources.py::_require_current_generation` through `_assert_active_lease`, but the resource
  JSON-RPC contract carries no lease token at all, so those calls pass a named, documented
  `require_token=False`. They therefore still accept "the generation matches and *some* lease is
  active" rather than "this caller holds *the* lease". That is the same
  defence-weaker-in-the-sibling shape the review is about, and it cannot be closed inside the
  addon: it needs a contract change on both the Odoo and the n8n side so the token travels with
  the request. Owner: **R2 Task 8** (added).
- **The live Odoo-18 stack still carries the expired-lease hole.** The fix landed in
  `odoo/addons/`; `odoo/addons18/` serves the running system and now diverges. Decision §3.4
  governs whether that port receives the fix or is deleted — until that decision is executed, the
  live system is running the unfixed code. This is a live-system fact, not a branch defect.
- **Bounded exception to the compose freeze.** The Foundation plan forbids editing
  `docker-compose.yml` before the Odoo-19 handoff gate. R1 Task 1 changed exactly one line there:
  the backend service's `CORS_ORIGINS` key, renamed to `PWA_ORIGINS` because that setting was
  removed and the container would otherwise fail to start. This touches no database, role, volume
  or network surface and therefore nothing the handoff gate governs. Recorded here rather than
  left as a silent violation; R4 Step 9 remains the only other sanctioned compose change.
- **Plan defect, corrected:** both remediation plans specified `docker compose exec odoo` as the
  Odoo test command. That container is **Odoo 18** and mounts `odoo/addons18`. The v19 addon lives
  behind the `odoo19-trial` compose profile. Every plan has been corrected; any earlier claim of a
  green v19 suite obtained with `compose exec odoo` tested the wrong addon.

### Carried forward from earlier task reviews

- `_transition()` accepts `queued -> retry_scheduled` without the recovery side effects — see §3.3.
- The ZPL command allowlist exists in both backend Python and the Odoo addon. Deliberate
  second-boundary defence, real drift risk. Either generate both from one declarative source or
  add a test that fails when they diverge.
- The v2 verifier is a static allowlist checker, not a data-flow analyser. Renamed or
  case-varied field names and payloads assembled at runtime are accepted bypass classes,
  documented in its docstring.
- Task 9 lane: no real n8n delivery, and the dispatcher has never run against real Odoo RPC.
- Task 10 lane: every Odoo interaction is a test double, so a wrong RPC key name surfaces as a
  409 rather than a test failure.
- Task 11 lane: artifact PDFs may not embed JPEG or CCITT raster images. If that ever needs
  revisiting, the fix is an intrinsic-dimension check, never a return to trusting declared
  dimensions.

## 5. Whole-branch gate

Before the branch is approved again, all of the following must be green in one run on the merged
tree, and each must be recorded here with its result:

- full backend suite
- full Odoo-19 addon suite, including the new multi-cursor concurrency tests
- the v18 auth-port suite, if that port survives decision §3.4
- n8n node tests, the adversarial verifier fixtures, and a credential-bound import
- an empty-volume PostgreSQL bring-up and a full migration plus rollback against a disposable
  cluster
- hostile-origin browser tests (Task 16)
- a crash-after-external-effect drill (Task 15)
- the two-database, restart and contention gate (Task 17)
