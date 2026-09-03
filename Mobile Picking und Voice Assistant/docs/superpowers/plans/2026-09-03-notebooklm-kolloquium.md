# NotebookLM Colloquium Learning Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create, verify, humanize, and upload exactly 22 German Markdown sources covering eleven colloquium areas with 330 answered professor questions.

**Architecture:** Each subject is an independent pair consisting of one 10–11-page learning text and one 30-question examination file. Topic workers inspect primary project evidence and write their pair; the main agent owns the shared template, cross-topic consistency, authentication, final validation, and NotebookLM mutations.

**Tech Stack:** Markdown, Git, `rg`, shell validation, `blader/humanizer`, `gemini-notebook-mcp-cli` (`nlm`), NotebookLM.

**Spec:** `docs/superpowers/specs/2026-09-03-notebooklm-kolloquium-design.md`

## Global Constraints

- Produce exactly 22 Markdown files: eleven learning texts and eleven question files.
- Produce exactly 30 distinct questions per subject and 330 questions overall.
- Explain every newly introduced technical term and every named project-specific API, route, important method, and function.
- Cite current code, configuration, tests, runtime evidence, thesis material, or official documentation close to each factual claim.
- Distinguish implemented behavior, documented intent, inference, and known gaps.
- Humanizer may change prose but must not change facts, identifiers, commands, citations, or technical meaning.
- Run no more than three topic workers concurrently and normally no more than five distinct subagents overall.
- Only the main agent may authenticate, create or mutate the NotebookLM notebook, or upload sources.
- Do not expose an MCP HTTP endpoint, share the notebook, delete an existing notebook, or print authentication material.

## File Map

Create all deliverables under:

`/home/endri/mobile-picking-handoffs/2026-09-03/notebooklm-kolloquium/`

The exact 22 names are the eleven `*-lerntext.md` and eleven `*-fragen.md` names listed in the spec. Temporary inventories and review notes stay outside this directory so NotebookLM receives only final sources.

---

### Task 1: Tooling, authentication, and common writing contract

**Files:**
- Reference: `docs/superpowers/specs/2026-09-03-notebooklm-kolloquium-design.md`
- Reference: `/home/endri/mobile-picking-handoffs/2026-09-03/KOLLOQUIUM-FRAGEN-HANDOFF.md`
- Create temporarily: `/tmp/notebooklm-kolloquium-source-map.md`

**Interfaces:**
- Consumes: approved design and existing colloquium handoff.
- Produces: working `humanizer` skill, working `nlm` CLI, authenticated local NotebookLM session, source map, and one writing contract supplied verbatim to every topic worker.

- [ ] Verify the current `blader/humanizer` release and inspect its complete `SKILL.md` before installation.
- [ ] Install Humanizer through the Codex skill installer, reload or read the installed skill as required, and record its version.
- [ ] Install `notebooklm-mcp-cli` with `uv tool install notebooklm-mcp-cli`; verify with `nlm --version` and `nlm --help`.
- [ ] Run `nlm login`; stop for the user's password, MFA, consent, or ambiguous account selection, then verify the authenticated account without printing cookies or tokens.
- [ ] Inventory thesis documents, requirements, architecture docs, source directories, tests, evaluation results, and relevant runtime checks into `/tmp/notebooklm-kolloquium-source-map.md`.
- [ ] Define the common heading structure from the spec and the citation form `Quelle: relative/path:line — symbol or evidence`.
- [ ] Create the deliverable directory and verify that it is empty before topic work begins.

### Task 2: Wave 1 — subjects 01 to 03

**Files:**
- Create: `01-gesamtarchitektur-lerntext.md`, `01-gesamtarchitektur-fragen.md`
- Create: `02-pwa-scanning-lerntext.md`, `02-pwa-scanning-fragen.md`
- Create: `03-fastapi-python-lerntext.md`, `03-fastapi-python-fragen.md`

**Interfaces:**
- Consumes: common writing contract and topic-specific entries in the source map.
- Produces: three complete, independently reviewable file pairs.

- [ ] Dispatch three topic workers concurrently, one pair per worker.
- [ ] Require each worker to trace the real code flow before drafting and to return its source inventory with the pair.
- [ ] Review each pair for spec compliance, factual accuracy, 30-question count, non-duplicated questions, and oral-answer usefulness.
- [ ] Return corrections to the same worker and repeat review until accepted.
- [ ] Commit only the six accepted files.

### Task 3: Wave 2 — subjects 04 to 06

**Files:**
- Create: `04-odoo-orm-postgresql-lerntext.md`, `04-odoo-orm-postgresql-fragen.md`
- Create: `05-claim-heartbeat-idempotenz-lerntext.md`, `05-claim-heartbeat-idempotenz-fragen.md`
- Create: `06-docker-caddy-netzwerke-lerntext.md`, `06-docker-caddy-netzwerke-fragen.md`

**Interfaces:** Same writing contract and acceptance gate as Task 2.

- [ ] Reuse the three established workers, assigning one new pair to each.
- [ ] Review Odoo versus PostgreSQL responsibility, claim versus idempotency, and public versus internal network boundaries especially closely.
- [ ] Correct unsupported claims and duplicate questions through follow-up tasks.
- [ ] Commit only the six accepted files.

### Task 4: Wave 3 — subjects 07 to 09

**Files:**
- Create: `07-n8n-outbox-ereignisse-lerntext.md`, `07-n8n-outbox-ereignisse-fragen.md`
- Create: `08-sprache-ki-qualitaet-lerntext.md`, `08-sprache-ki-qualitaet-fragen.md`
- Create: `09-sicherheit-fehlerfaelle-lerntext.md`, `09-sicherheit-fehlerfaelle-fragen.md`

**Interfaces:** Same writing contract and acceptance gate as Task 2.

- [ ] Reuse the workers for one pair each.
- [ ] Verify asynchronous outbox states, deterministic versus model-based decisions, trust boundaries, and failure behavior against primary evidence.
- [ ] Correct unsupported claims and duplicate questions through follow-up tasks.
- [ ] Commit only the six accepted files.

### Task 5: Wave 4 — subjects 10 and 11

**Files:**
- Create: `10-tests-evaluation-lerntext.md`, `10-tests-evaluation-fragen.md`
- Create: `11-wissenschaft-reflexion-lerntext.md`, `11-wissenschaft-reflexion-fragen.md`

**Interfaces:** Same writing contract and acceptance gate as Task 2.

- [ ] Assign the two pairs to two established workers concurrently.
- [ ] Require explicit separation of what tests demonstrate, what mocks cannot demonstrate, measured results, interpretation, limitations, and unverified claims.
- [ ] Correct unsupported claims and duplicate questions through follow-up tasks.
- [ ] Commit only the four accepted files.

### Task 6: Cross-pack factual and structural validation

**Files:**
- Modify only when correcting: all 22 deliverable files.

**Interfaces:**
- Consumes: 22 accepted topic files.
- Produces: structurally complete and mutually consistent source pack.

- [ ] Confirm exactly 22 Markdown files with `find ... -maxdepth 1 -name '*.md' | wc -l`; expected output: `22`.
- [ ] Count numbered question headings per `*-fragen.md`; expected output: `30` for every file and `330` overall.
- [ ] Search for unfinished drafting markers, broken absolute source paths, uncited factual sections, and duplicated question headings; correct every finding.
- [ ] Cross-check repeated descriptions of Caddy, FastAPI, Odoo, PostgreSQL, claims, idempotency, n8n, local AI, security, and testing for contradictions.
- [ ] Check that all named project functions and methods have an explanation of responsibility, inputs, result, and caller where relevant.
- [ ] Run a link/path verifier against every local citation and manually review a sample from each file.
- [ ] Commit factual and structural corrections.

### Task 7: Humanizer editorial pass

**Files:**
- Modify: all 22 deliverable files.

**Interfaces:**
- Consumes: factually approved source pack.
- Produces: natural German prose with unchanged technical content.

- [ ] Run Humanizer on one representative learning text and compare facts, identifiers, commands, and citations before and after.
- [ ] If the pilot preserves all protected content, run the same draft–audit–rewrite workflow across the remaining files.
- [ ] Re-run the structural, question-count, citation-path, identifier, and unfinished-marker checks from Task 6.
- [ ] Inspect each file for generic AI phrasing, excessive headings, repetitive transitions, and unnatural sentence rhythm.
- [ ] Commit only the reviewed editorial changes.

### Task 8: Notebook creation and source upload

**Files:**
- Read: all 22 deliverable files.

**Interfaces:**
- Consumes: authenticated `nlm` session and final source pack.
- Produces: one new private NotebookLM notebook containing 22 processed sources.

- [ ] Re-verify the selected NotebookLM account and list existing notebooks without changing them.
- [ ] Create one new private notebook with an unambiguous colloquium title and capture its notebook ID without exposing credentials.
- [ ] Upload the 22 Markdown files as individual sources.
- [ ] Poll source processing status and retry only failed uploads without duplicating successful sources.
- [ ] Compare the notebook source list against the exact local 22-file manifest; expected missing and extra counts: `0` and `0`.
- [ ] Ask two cross-topic questions and verify that NotebookLM cites the uploaded sources rather than inventing unsupported project facts.

### Task 9: Learning artifacts and final acceptance

**Files:**
- Read: all 22 deliverable files.

**Interfaces:**
- Consumes: fully processed NotebookLM notebook.
- Produces: available chapter learning artifacts and an evidence-backed completion report.

- [ ] Query account capabilities for quiz, flashcard, audio, report, mind-map, slide, infographic, and data-table generation.
- [ ] Create one quiz and one flashcard set per subject when the account supports them, using only the matching file pair as grounding instructions where the CLI permits.
- [ ] Create a small set of thematic audio overviews covering all eleven subjects without producing redundant audio per chapter.
- [ ] Create one cumulative oral-exam simulation grounded in all 22 sources.
- [ ] Verify artifact status and record any entitlement, quota, or generation failures without claiming success for unavailable artifacts.
- [ ] Report the notebook title/ID, source count, artifact inventory, validation results, and the exact local deliverable directory.
