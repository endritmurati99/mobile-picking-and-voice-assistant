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
| M1 | ~~`session.py:111` can return a concurrently revoked or expired session once more during role marking~~ **RE-SEVERITY 2026-07-30: the description understated it. `api_mark_roles_checked` had NO revocation or expiry check at all — it reproduces with no concurrency whatsoever.** A session revoked minutes earlier on a separate committed transaction is silently re-blessed, handed back via `_api_payload()` with `roles`/`expires_at`/`revoked_at`, and has a fresh `roles_checked_at` **plus the caller's requested roles written onto it**. So: revoked session stays usable, and role escalation is writable onto a dead session. | ~~Minor~~ **High** | R2 | **yes — pre-image of `session.py:214-261`, verified by the Task 7 reviewer** |
| M2 | The nonce GC deletes at most 1000 rows per ten minutes and reports no remainder | Minor | R2 | **yes — verified during Task 7** |
| M3 | Product images are anonymous and instance-selectable under the default-on development grace | Minor | R1 (closed by #1) | yes |

### Closed by remediation (status 2026-07-30)

Each entry below passed its task review, its fix rounds, and the lane's whole-branch review. The
commits are on the lane branches; nothing is merged yet.

| # | Owner | Closed by | Evidence |
|---|-------|-----------|----------|
| 1 | R1 Task 1 | `1943b1c`..`9208866` | `runtime_profile` is an enum; `reject_wildcard_origins_with_credentials` takes no profile argument by construction. Five fix rounds. Residual: compose still defaults the variable to `development` — see below. |
| 2a | R1 Task 1 | `1943b1c`..`9208866` | CORS derives solely from `pwa_origins` (`main.py:101-108`); whole-branch reviewer confirmed one middleware entry with `allow_credentials=True` and a validated origin list. |
| 8 | R1 Task 2 | `145ef9f` | All five `@router.post` in `n8n_internal.py` on `Depends(get_legacy_n8n_workflow_service)`; reviewer confirmed there is no sixth route. |
| 9a | R1 Task 3 | `879037f`..`a25d932` | Four fix rounds; closed structurally in round 4 — one `_pdf_walk`, two stackless views, container table derived from ISO 32000-1 §7.3. An adversarial reviewer built eight container/aliasing attacks and could not get one accepted. |
| 3 | R3 Task 1 | `1e240f5`..`65265a3` | Ten stated obligations with a real domination computation. The whole-branch reviewer wrote ten independent bypass attempts; nine were rejected with the correct cause. |
| 12 | R3 Task 2 | `65265a3`..`43f35d4` | Generation field closed; `KNOWN_GENERATIONS` is one declaration both readers import. |
| 13 | R3 Task 3 | `43f35d4`..`4b5a4b0` | Wire format unified; the seam is pinned from both sides. |
| 16 | R3 Task 3 | `43f35d4`..`4b5a4b0` | Single `open()` with `O_NOFOLLOW\|O_NONBLOCK` then `fstat` on that descriptor — **stronger than the plan specified**, which would have left a `lstat`-then-`readFile` TOCTOU open. |

Still open and unchanged by the above: **#9b** (the Odoo-side byte denylist) belongs to R2 Task 9,
not to R1, despite the owner column above reading `R1`. **#7** is in R2 Task 4, in its fix loop at
the time of writing.

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

### Raised during remediation (2026-07-30)

- **#17 — the stream expansion budget does not cover object streams or cross-reference streams.**
  Important. Owner: unassigned, needs a lane. **Pre-existing — it predates the remediation base
  `1e240f5` and no lane introduced it.** Both PDF traversals root at the catalog, so a
  `/Type /ObjStm` is never a `_pdf_nodes` node and never reaches `_consume_stream_budget`
  (`binary_validation.py`, `validate_pdf:988-993`) — yet pypdf inflates it eagerly the moment
  `reader.trailer["/Root"]` is resolved at `validate_pdf:963`, before the graph walk exists to
  police it. The same argument applies to the xref stream.
  Reproduced independently twice, by the R1 Task 3 round-4 re-reviewer and again by the R1
  whole-branch reviewer building its own PoC from scratch: a **65,588-byte** file whose `/ObjStm`
  inflates to **64 MiB** is **ACCEPTED** in 2.6 s at 160 MiB peak RSS, while
  `MAX_PDF_EXPANDED_BYTES` is 32 MiB. It scales linearly — a 522,186-byte file is accepted at
  537 MiB inflation, 20.8 s and **1,057 MiB peak RSS** — so extrapolating to `MAX_DOCUMENT_BYTES`
  (10 MiB) gives roughly 10 GB of inflation and several minutes of CPU. Confirmed identical at base
  `1e240f5`.
  **Calibrated as Important, not Critical, because it is authenticated.** `n8n_v2.py:404-424` runs
  `precheck_artifact` (phase 1, cheap) → `_reserve_signed_nonce` → `validate_artifact` (the
  expensive parse), so the bomb detonates only after HMAC signature verification and nonce
  reservation. A compromised or buggy n8n can exhaust the backend; an internet attacker cannot.
  This is a **flate-bomb boundary, a different class from finding #9a's inline-image boundary**.
  Fixing it means adding a pre-parse xref/ObjStm inspection pass — comparable in size and risk to
  the whole of R1 Task 3, which took four fix rounds. Deliberately registered rather than bolted on
  at merge time.
- **Plan defect — R1's exit gate pointed it at a file it never had.** The R1 plan (line 683)
  requires marking findings #1, #2a, #8, #9a, #9b and M3 closed in this file, and R1 Task 3 Step 4
  cites decision §3 of it. This file does not exist on `remediation/r1-backend`: it was introduced
  in `7a65183`, which is not an ancestor of `a25d932`, and lives only on `remediation/r2-odoo`. The
  register must therefore be updated at integration, on the branch that actually carries it — as
  this entry does. Recorded so the next plan does not repeat the shape.
- **Residual, previously adjudicated, not reopened: `RUNTIME_PROFILE` defaults to development in
  compose.** `docker-compose.yml:155` is `${RUNTIME_PROFILE:-development}`, and
  `validate_runtime_security` (`config.py:287-288`) returns immediately for any non-production
  profile — so a deployment that forgets the variable skips origin validation, the HTTPS
  requirement on origins, and credential-strength checks on the n8n and session secrets, with a
  single WARNING as the only protection. R1 Task 1 round 1 decided to warn rather than fail and
  that decision stands. The one-character hardening for a real deployment is
  `${RUNTIME_PROFILE:?set to production for a real deployment}`. Belongs with the deployment work.

### Deployment obligation created by remediation lane R2

- **Lease tokens now appear in access logs and in n8n execution data.** R2 Task 8 closed #5b's Odoo half by
  carrying the `processing_lease_token` as a **signed path segment**:
  `GET /instances/{i}/jobs/{j}/leases/{token}/media/{m}` and `POST .../leases/{token}/events/{e}/artifacts/{k}`.
  The token is genuinely inside the signed bytes — `verify_n8n_to_backend_request` signs against
  `request.scope["raw_path"]`, and a target mismatch is a 401 — and no application code logs it. But a URL
  path is logged where a JSON body was not, at three concrete sinks in this repo: Caddy's server-level
  `log { output stdout }` covering `handle /api/*` (`infrastructure/caddy/Caddyfile:4-6`, `34-37`), uvicorn's
  access log at `--log-level info` (`docker-compose.yml:162`), and n8n's persisted execution data, which
  stores the built URL.
  **This was the right trade on the alternatives available** — extending the shared canonical signature input
  touches every v2 route's replay primitive, a JSON envelope breaks Task 11's raw-bytes invariant, and a
  query string is refused outright by `verify_signature` (`hmac_signing.py:88-89`). The blast radius is
  bounded: the token is a lease-scoped, expiring capability, useless without the HMAC key, and it never
  reaches a browser. **The obligation is to decide explicitly rather than inherit it silently:** either accept
  lease tokens in those three log sinks, or add path redaction at the Caddy and uvicorn layers and cap n8n
  execution-data retention. Raised by the Task 8 re-reviewer, which insisted it be written down before #5b is
  ever marked closed.
- **`models/resources.py` has four `FOR UPDATE` sites and no SQLSTATE-40001 classification.** Pre-existing
  from the Task 1/3 era, confirmed absent at `ad8df7c` as well. Every other locking model in the addon
  carries the lane pattern (`receipts.py:436`/`742`, `integration_job.py:266`, `outbox.py:233`,
  `session.py:128`). Task 8 edited one of these lock statements and widened it to multi-row without adding
  the pattern. Lane-level cleanup, not a Task 8 defect.

### Deployment obligation created by remediation lane R3

- **Compose `secrets:` must set `uid`, `gid` and `mode`.** R3 Task 3 moved the credential-file
  permission check into the container, immediately before the read, using `lstat`. It requires the
  mounted secret to be a regular file, mode `0400`, owned by the `node` runtime user.
  `docker-compose.yml` currently declares **no `secrets:` block at all**, and Docker's default for
  mounted secrets is root-owned `0444` — which the new check rejects on both counts. Whoever wires
  the compose `secrets:` block (Task 15, or whoever deploys first) must set `uid`, `gid` and `mode`
  explicitly, or credential provisioning will refuse to start. This is a deliberate fail-closed
  choice, not an oversight: a secret readable by every process in the container is not a secret.

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
