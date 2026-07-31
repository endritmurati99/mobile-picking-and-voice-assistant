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
| 8 | Atomic Odoo jobs, outbox, receipts, leases | done, R2 defects closed |
| 9 | Backend-to-n8n event transport | done, R2 defects closed |
| 10 | Signed v2 routes | done |
| 11 | Job-bound media and artifact contracts | done, R1/R2 defects closed |
| 12 | Odoo-19 core idempotency handoff | **STARTABLE** — `wave1-odoo19-handoff` placed 2026-07-31 on `e8742b4` |
| 13 | Postgres role separation | **live acceptance PARTIAL** — see the R4 entry; two endpoints are not achievable as specified |
| 14 | n8n credential management | done, R3 defects closed |
| 15 | Custom n8n image, network boundaries, Caddy, TLS | **STARTABLE** — 12's gate is open; scope amended, see §3, and it inherits four things the cutover deliberately did not do |
| 16 | Production route surface and browser idempotency | **security half DONE** (`27c58c0`) — **finding #2b is CLOSED**; the `RuntimeServices` half is not started |
| 17 | Two-database, concurrency, restart, rollout gates | blocked by everything above |

### The Odoo-19 cutover was EXECUTED on 2026-07-31

Tag `wave1-odoo19-handoff` is on `e8742b4`, branch `integration/foundation-remediation` — placed on the
verified post-cutover state rather than on the merge commit of `codex/odoo19-cutover`, because the
cutover was executed on top of that merge and the tag should name a state that was *proven*, not one
that was merely mergeable.

Commits: `ee9171f` (the atomic commit — `odoo/addons18/` deleted and Compose reworked together),
`1f334dc` (every image pinned by digest, `RUNTIME_PROFILE` fail-closed), `bb00213` (the seeder ported
to Odoo 19), `e8742b4` (defaults and docs repointed).

Handoff evidence: H1 `addons18/` gone, zero tracked files. H2 the `odoo` service builds
`odoo:19.0@sha256:e415f992…` and mounts `./odoo/addons`. H3 no `odoo19-trial` profile remains. H4 the
addon suite run **from the productive image**, with the live `odoo` stopped: `0 failed, 0 error(s) of
128 tests`. H5 `masterfischer_o19` and `lager2_o19` seeded, `picking_assistant_integration
19.0.1.0.0 installed`. H7 `masterfischer` 66/46 and `lager2` 9 intact, both still `base 18.0.1.3`.
H8 `db_name` set in both new config files. Live chain proven end to end: the backend container's own
`OdooClient` read real pickings out of `masterfischer_o19`. Backend suite 750 passed.

**Two paths were proved dead before the reseed was accepted, and both proofs are worth keeping:**
1. **Clone-and-upgrade fails on this image.** `-u all` runs
   `ALTER TABLE ir_model ALTER COLUMN state TYPE jsonb USING state::jsonb` and dies with
   `invalid input syntax for type json, Token "base" is invalid`. Reproduced on three throwaway
   restores, isolated to stock Odoo addons only and to a `lager2` copy as well, and root-caused: the
   image demands a schema its own fresh initialisation does not produce (`ir_model.state` is
   `varchar` in a fresh v19 init).
2. **`masterfischer_o19_trial` is not a template.** It carries the same `database.uuid` as
   `masterfischer`, so it really is an upgraded copy — but made on 2026-07-04 with a tool that is not
   in this repository, and it has since diverged: 698 `stock_move_line` rows against 420, 6 active
   users against 7, and `picking_assistant_integration` **not installed**.
   `seed-odoo.py` was also **not** a v19 seeder despite its docstring; five incompatibilities were
   found and fixed, each proved against a running v19 server (`stock.move.name` removed,
   `res.users.groups_id` → `group_ids`, a hardcoded `product_uom`, `action_apply_inventory` returning
   `None` through a marshaller that forbids it — which made the seeder report 15 skipped bookings it
   had in fact committed — and a dead module check swallowing a `KeyError`).

**Executed answers to §3.4 and the gate:** the Odoo-18 port did **not** survive — it is deleted, so
the whole-branch gate line *"the v18 auth-port suite, if that port survives decision §3.4"* is
**struck, not pending**. Two standing live-system exposures are thereby **resolved by execution**:
production no longer runs the unfixed `_lock_or_create` throttle path, nor the **High** M1
session-revocation hole.

**Operator actions still owed on the live stack:** the admin password on both v19 databases is still
the fresh-init default `admin`, and `RUNTIME_PROFILE` is still `development`, so
`validate_runtime_security` returns immediately and the backend says so at every start. The rollback
window stays open until submission by the owner's decision — `masterfischer`, `lager2`, the dumps and
the filestores all remain.

**One caveat on the smoke test, recorded rather than hidden:** `infrastructure/scripts/test-api.py`
reports 5/7. Both failures are `401 Ungueltige oder abgelaufene Sitzung` on `/api/pickings` and
`/api/quality-alerts` — the script still authenticates the pre-remediation way, and
`mobile_header_grace_mode` now defaults to `False` (that default was finding #1). This is the
hardening working as designed, not a cutover regression: `/api/health` and both `scan/validate` cases
pass, and the direct `OdooClient` read proves the Odoo path. The smoke script needs updating for
session-based auth; nearest owner is Task 16.

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

### Integration day — 2026-07-31

**All three remediation lanes are complete and they merge with ZERO textual conflicts.** Branch
`integration/foundation-remediation` off `1e240f5`, merging `remediation/r1-backend`,
`remediation/r3-n8n` and `remediation/r2-odoo` in that order. A cross-lane adversarial review
(verdict `MERGE_SOUND_WITH_FINDINGS`) re-derived every number below rather than trusting the
controller.

Merged-tree results: backend **749 passed**; infrastructure **107 passed + the 1 known R4 failure**
(`test_no_app_uses_cluster_bootstrap_role_in_compose`); `node --test n8n/tests/*.test.mjs`
**46 passed**; `verify-workflows.py` **exit 0**. `odoo/` in the merge is byte-identical to
`remediation/r2-odoo` and `n8n/custom-nodes/` to `remediation/r3-n8n`.

**The lanes are disjoint at file level — the clean merge is structural, not luck.** Pairwise
intersections of the changed-file sets are all empty: R1 14 files, R2 28, R3 30, R1∩R2 = R1∩R3 =
R2∩R3 = ∅. R1 owns `config.py`/`main.py`/`dependencies.py`/`n8n_internal.py`, R2 owns
`n8n_v2.py`/`auth_sessions.py`/`outbox_dispatcher.py`/`odoo/`, R3 owns
`workflow_*`/`infrastructure/`.

**No test was lost in the merge.** Verified by comparing collected test-*id sets*, not counts:
base 540, R1 +189, R2 +13, R3 +4, zero removed by any lane.

**The backend↔Odoo lease-token seam is consistent.** `api_get_job_media` and
`api_store_job_artifact` have exactly one backend call site each (`routers/n8n_v2.py:390`, `:475`),
both passing `processing_lease_token` last-positional, matching `models/resources.py:453`, `:475`.
No other caller exists anywhere in the repo.

Findings raised by that review, none of them caused by the merge itself:

- **The v2 verifier is dormant, so `verify-workflows.py` exit 0 proves nothing about v2.** All
  eight registry workflows are generation `v1`; the run ends `Skipped v2 checks for 8 workflow(s)`.
  `load_event_targets` therefore returns an empty dict. Findings #3, #12 and #16 are closed in code
  and covered by R3's own fixtures, but the merged green gate exercises none of them against real
  registry data. Owner: Task 15, which owes the first v2 workflow.
- **R2's new lease-token URL shape has no client anywhere in the repo.** Nothing under `n8n/`
  builds `/leases/{token}/media/...`; the custom node only *verifies* inbound backend→n8n
  signatures, it never builds an outbound signed request. Whoever writes that workflow must sign
  `raw_path` including the URL-encoded lease segment, and `verify_signature` refuses query strings
  outright, so getting it wrong yields a blanket 401 with no partial-success signal. This is #5b's
  missing third half. Owner: Task 15.
- **M1 is closed on the branch, not in the default deployment** — confirmed unchanged by the merge.
  `addons/.../session.py:132-151` carries the full fix; `addons18/.../session.py:111-122` is the
  unfixed pre-image, and compose mounts `addons18` into both `odoo` and `odoo-lager-2` while the
  backend's `ODOO_URL` points at the former. `addons18` also lacks `integration_job.py`,
  `outbox.py`, `receipts.py` and `resources.py` entirely. Closed only by the Odoo-19 cutover.
- Minor: the credential-file permission check is double-implemented and the two rules disagree
  (`provision-n8n-credentials.sh:83-90` wants mode exactly 600/400 plus an owner name;
  `provision-credentials.mjs:128-132` wants `mode & 0o077 == 0` and `uid == getuid()` — `0700`
  passes one and fails the other). The R3 deployment obligation below **overstates** what the code
  enforces. Being unified in R3.
- Minor: `pwa_origins` is parsed twice — `parse_origins()` in `config.py`/`main.py`, and a
  hand-rolled `split(",")` at `dependencies.py:107`. Being unified in R1.
- Minor: `.env.example` carries neither `PWA_ORIGINS` nor `RUNTIME_PROFILE` after R1's rename.
- Minor: latent `tests`-package shadowing — `workflow_registry.py` inserts `backend/` at
  `sys.path[0]`, `backend/tests/__init__.py` exists, `infrastructure/tests/` has none. Dormant
  while the suites run separately.

**R2's whole-branch fix wave was re-reviewed** (`69c1fe8..e6c08ce`, verdict
`APPROVED_WITH_FINDINGS`, no Critical). The reviewer re-ran the census itself: **16 blocking
`FOR UPDATE` sites, 3 excluded as `SKIP LOCKED`, 6 classified, 10 previously unclassified** — so
the "17" in the register above was the brief's error, not the code's, and is corrected here. The
TRANSITIONS table is confirmed frozen at merged HEAD: net one removal, zero additions across the
whole lane. No eighth blind guard. Two Importants were fixed in `69ae9b4` (addon suite 126 → **128
green**, backend 556 green):
- `outbox.py::_owned_lease` — the transparent-retry argument had no story for *exhausted* retries
  at the highest-contention site in the addon. The implementer read the Odoo runtime rather than
  inferring it (`service/model.py:30`, `MAX_TRIES_ON_CONCURRENCY_FAILURE = 5`, then the original
  `SerializationFailure` is re-raised unclassified) and chose to document rather than classify,
  because classification *removes* the retry and would answer "lease is not owned by this worker"
  on the first lost lock, and because the only production caller
  (`outbox_dispatcher.py:155-191`) handles a 409 and a 500 in the identical branch.
- `TestCronProgressGuard` tested only half its name. Deleting the `_report_cron_progress` call
  outright left both pre-existing tests green; the two new ones fail with `0 != 1`.

### Odoo-19 cutover — facts established 2026-07-31, and the owner's decisions

Read-only queries against the live cluster, run by the controller:
- **`masterfischer` is Odoo 18. Confirmed, not inferred:** `base = 18.0.1.3`, `stock = 18.0.1.1`,
  `picking_assistant_integration = 18.0.1.0.0`. There is no "already v19" escape hatch.
- Databases on the one shared cluster: `lager2`, `masterfischer`,
  `masterfischer_o19_foundation_test`, `masterfischer_o19_trial`, `n8n`, `odoo19_smoke_codex`,
  `picking`, `postgres`.
- **What `masterfischer` holds:** `stock_picking` 66 (46 `done`, 20 `assigned`), created
  2026-03-22 .. 2026-07-25; `stock_move_line` 420; `res_partner` 9; `product_product` 54;
  `res_users` 7; `mail_message` 1558 spanning 2025-01-13 .. 2026-07-25. `sale_order` and
  `account_move` do not exist as tables — sale and accounting are not installed. So: thesis
  working data, no customer or accounting records.
- Odoo Community has no in-place major upgrade, and this repo contains no OpenUpgrade and no
  `migrations/` directory. **The cutover is a reseed**, via the existing
  `infrastructure/scripts/seed-odoo.py` ("Seed-Daten für Odoo 19 Community").
- `odoo-lager-2` also mounts `./odoo/addons18` (`docker-compose.yml:88`), so it belongs in the same
  atomic commit — wider than the original constraint stated.
- Nothing is digest-pinned (`grep -c "@sha256"` = 0). Floating: `caddy:2-alpine` (twice),
  `postgres:16-alpine`, the Odoo build args; `:latest` for whisper and ollama. Only n8n is
  tag-pinned, at 2.13.3.

**Owner decisions, 2026-07-31** — these are decisions, not proposals:
1. **Reseed into a new database `masterfischer_o19`, and `masterfischer` is NOT deleted.** It stays
   on the cluster as both the rollback path and the queryable archive of the 66 pickings. The 46
   completed pickings will not be visible in the new stack; nothing is destroyed. No cutover step
   may drop or overwrite it.
2. **`odoo-lager-2` migrates to v19 too**, in the same commit, with its own freshly seeded v19
   database; its v18 databases are likewise kept.

Plan: `docs/superpowers/plans/2026-07-31-odoo19-cutover.md` on branch `codex/odoo19-cutover`.

### R4 — finding #14, status 2026-07-31

Task 1 landed (`ac335a1`): `init-n8n-db.sql` is self-sufficient again, and the Task-13 hardening is
parked, unmounted, in `init-n8n-db-hardening.sql` beginning with `\connect n8n`. Its adversarial
review returned `APPROVED_WITH_FINDINGS` — the substantive fix is correct and purely additive, but
both widened guards were shown to be **vacuous against the tree as shipped** (the only `GRANT … TO`
target is `:"owner"`, which the analyser deliberately skips, so guard 1's loop body never runs and
guard 2 executes zero assertions), and nine of fifteen hand-built broken-script shapes got through
— including `\connect` placed *after* the statement it is supposed to protect, `\connect postgres`,
and a `\connect` appearing only in a trailing comment. Those are in a fix round.

**The live empty-volume probe (plan Step 5, "not optional and cannot be stubbed") was run by the
controller and PASSES.** Throwaway project `pwr-freshinit`, `POSTGRES_HOST_PORT=5434` to dodge the
live stack: init completed with no error and the `n8n` database was created. A second run with
`POSTGRES_USER=probeowner` produced an `n8n` database owned by **probeowner** — so the
`\set owner odoo` + `\getenv owner POSTGRES_USER` + `:"owner"` construction genuinely honours the
environment on a real psql and does not fall back to the literal. Both projects torn down with
`down -v`. Operational note for anyone repeating it: `docker.exe` needs a **Windows** path
(`wslpath -w`), and exported shell variables do not reach it without `WSLENV`, so overrides must go
in the env file.

Finding #14 is therefore **remediated, pending only the fix round's review**.

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
- **40001 classification holds at 6 of 17 blocking `FOR UPDATE` sites — and the gap is NOT confined to
  `resources.py`.** An earlier version of this entry said the rule held everywhere except `resources.py`.
  **That was wrong**, and the R2 whole-branch review corrected it with a full census at HEAD (excluding
  `SKIP LOCKED`, which cannot raise 40001):
  *Classified:* `integration_job.py:277`, `outbox.py:245`, `receipts.py:450`, `receipts.py:754`,
  `session.py:136`, and `auth_throttle.py:76` (deliberately unclassified with its reasoning in the code —
  the login path wants Odoo's transparent retry).
  *Unclassified:* `outbox.py:111` (`_owned_lease`, the ack/nack hot path), `outbox.py:227` (requeue's job
  lock), `receipts.py:327` (`_lock_existing`), `receipts.py:393` (acceptance job lock), `receipts.py:618`
  and `:628` (callback job + receipt locks), and `resources.py:317`, `:332`, `:366`, `:489`.
  So the rule is broken **inside `receipts.py` and `outbox.py` — the two files where the pattern was
  invented.** Anyone who "fixes `resources.py`" per the old entry would have believed the rule then held.
  **Calibration:** an unclassified real 40001 carries a driver-populated `pgcode`, so Odoo's `retrying()`
  retries the RPC transparently — this is not a 500 in the ordinary case. The defect is **inconsistency**:
  the same logical race yields a silent retry at `receipts.py:393` and a clean 409 at `receipts.py:450`,
  in the same call graph, with nothing recording why. Fix by classifying the remaining eleven **or** by
  adding a one-line deliberate-choice comment at each, the way `auth_throttle.py:84-92` does.

- **The R2 Odoo half cannot ship without the backend half.** `api_get_job_media` and
  `api_store_job_artifact` now take `processing_lease_token` positionally with **no default**, so the
  pre-branch backend callers break on **every** call to both binary routes. It is fail-closed — Odoo
  serialises the server-side `TypeError` into an error envelope, `OdooClient._json_rpc` raises
  `OdooAPIError`, and the routes return a clean 409 rather than a 500 — but it is a total outage of those
  two routes until both halves ship together. Merging the branch is safe; deploying the addon alone is not.
- **`odoo/addons18/` still serves the live stack and still carries the unfixed `_lock_or_create` defect.**
  The lease fix's v18 divergence is recorded above; the **throttle** fix's is not. Until `addons18` is
  actually deleted per the Odoo-19-only decision, production is running the login path R2 Task 5 proved
  defective — including the M1 session-revocation hole, which was re-severitied to High.

### Deployment obligation created by remediation lane R3

- **Corrected 2026-07-31 — the rule is a mask, not a mode literal, and both halves now enforce it.**
  The earlier text below said "mode `0400`, owned by the `node` runtime user". The code enforced
  neither literal, and worse, the host preflight and the container boundary enforced *different*
  predicates: `provision-n8n-credentials.sh` demanded mode exactly `600` or `400`, while
  `provision-credentials.mjs` demanded `mode & 0o077 == 0` — so `0700` passed one and failed the
  other. Unified in `e777f91` onto one rule, stated once:
  > A credential secret file must be a regular file, must have **no group or other permission bits**
  > (`mode & 0o077 == 0`), and must be **owned by the account that reads it**.

  `0600`, `0400` and `0700` all pass; `0640` and `0604` do not. The owner half is namespace-local by
  construction: on the host it is `PWR_SECRET_OWNER` (default `root`); inside the container it is the
  uid the n8n process actually runs as. The host script is a **preflight**; the container script is
  the **security boundary** — it opens the file once with `O_NOFOLLOW|O_NONBLOCK`, `fstat`s that
  descriptor and reads only through it. Passing the preflight says nothing about what the boundary
  will see. The guard that pins this runs **both real implementations** over the same mode matrix and
  fails unless their verdicts agree; a source-text assertion would not have caught the divergence,
  since each file was internally consistent.
  **Still owed, and it has no owner yet:** the two owner halves can still conflict in a real
  deployment — a root-owned secret plus a non-root n8n process satisfies the host default and fails
  the container. That cannot be settled until the deployment path exists, because `docker-compose.yml`
  declares no `secrets:` block, mounts nothing at `/run/secrets`, and does not mount `./n8n/scripts`
  into the container. Until then neither half of #16 runs in anger.

- **CORRECTION 2026-07-31, measured: the recorded remedy does not exist in Compose.** Outside swarm
  mode, Docker Compose **ignores `uid`, `gid` and `mode`** on a secret — it warns and drops them. So
  "set `uid`, `gid` and `mode` explicitly" cannot be carried out, and the `secrets:` block now in
  `docker-compose.yml` is decorative. Two further measurements from the same session: a **missing**
  secret file does not fail `up`, it silently becomes a world-writable **directory**; and a bind
  mount from this Windows-hosted checkout arrives `0777 root:root` inside the container, which
  `read_secret` refuses outright, because `chmod` is a no-op on that drvfs mount. **The obligation
  stands, its remedy does not.** File-based secrets need swarm mode, a Linux-native checkout, or an
  entrypoint that materialises the files at the right mode inside the container. Until then
  `*_SECRET_FILE` stays opt-in and the backend uses direct environment variables.

- **Compose `secrets:` must set `uid`, `gid` and `mode`.** R3 Task 3 moved the credential-file
  permission check into the container, immediately before the read.
  `docker-compose.yml` currently declares **no `secrets:` block at all**, and Docker's default for
  mounted secrets is root-owned `0444` — which the new check rejects on both counts. Whoever wires
  the compose `secrets:` block (Task 15, or whoever deploys first) must set `uid`, `gid` and `mode`
  explicitly, or credential provisioning will refuse to start. This is a deliberate fail-closed
  choice, not an oversight: a secret readable by every process in the container is not a secret.

### Carried forward from earlier task reviews

- ~~`_transition()` accepts `queued -> retry_scheduled` without the recovery side effects — see §3.3.~~
  **CLOSED by R2 Task 2**, which removed that edge from `TRANSITIONS` outright (`integration_job.py:32-36`).
  R2 Task 6 later tried to add a `queued -> review_required` edge; its review proved no caller could reach
  it and it was reverted. Net change to the frozen table across all eight R2 tasks: one removal, zero
  additions.
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

## 5a. Gate run of 2026-07-31 on the merged tree

Branch `integration/foundation-remediation`, merge commit `5f8b433`, carrying
`remediation/r1-backend` `20965a1`, `remediation/r3-n8n` `e777f91` and `remediation/r2-odoo`
`e7ffef3`. Second merge of the day; still **zero textual conflicts**.

| Gate item | Result |
|---|---|
| full backend suite | **750 passed** |
| full Odoo-19 addon suite, incl. the multi-cursor concurrency tests | **0 failed, 0 errors of 128 tests** |
| n8n node tests (`node --test n8n/tests/*.test.mjs`) | **46 passed** |
| `verify-workflows.py` | **exit 0** — but see the dormancy caveat below |
| infrastructure suite | **121 passed** + the 1 known R4 failure |
| the v18 auth-port suite | **moot** — decision §3.4 resolved to *delete*, so there is no port to test |
| empty-volume PostgreSQL bring-up | **passed** (R4 Task 1 probe, recorded above) |
| full migration plus rollback against a disposable cluster | R4 Task 2, in progress |
| hostile-origin browser tests | Task 16, blocked by design |
| crash-after-external-effect drill | Task 15, blocked by design |
| two-database, restart and contention gate | Task 17, blocked by design |

The addon run was made with the only correct command (`--profile odoo19-trial run --rm --no-deps
-T`, `--workers=0 --max-cron-threads=0`) against `masterfischer_o19_foundation_test`, with the live
stack up. The `could not serialize access due to concurrent update` lines in that log are the race
tests provoking the collision on purpose — `test_concurrent_row_creation_never_raises_a_raw_typeerror`
is named for exactly that — and are not failures.

`odoo/` in the merged tree is byte-identical to `remediation/r2-odoo` and `n8n/custom-nodes/` to
`remediation/r3-n8n`, so the addon result above transfers, and the TypeScript custom-node tests
(run green on the R3 lane) were not re-run in the merged worktree, which has no `node_modules`.

**So the remediation gate is green. The Foundation gate is not, and cannot be** — its remaining
three rows belong to Tasks 15, 16 and 17, which are blocked behind the Odoo-19 handoff by design.
Two caveats that a green line above does not carry: `verify-workflows.py` exit 0 proves only that
the **v1** contract still holds, since all eight registry workflows are generation v1 and the v2
path is dormant; and every backend↔Odoo interaction in the pytest suites is a test double, so a
wrong RPC key name surfaces as a 409 rather than a test failure.

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
