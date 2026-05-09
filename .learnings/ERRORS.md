# Errors

Command failures and integration errors.

---

## [ERR-20260508-001] make_verify_workflows_python_missing

**Logged**: 2026-05-08T12:58:00+02:00
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
`make verify-workflows` failed in the current Linux/OpenClaw runtime because the Makefile calls `python`, but only `python3` is available.

### Error
```text
/bin/bash: line 1: python: command not found
make: *** [Makefile:81: verify-workflows] Error 127
```

### Context
- Command attempted from `Mobile Picking und Voice Assistant/`: `make verify-workflows`
- Direct `python` invocation also failed.
- Use `python3 infrastructure/scripts/verify-workflows.py` in this runtime or adjust Makefile later if desired.

### Suggested Fix
Either add a portable `PYTHON ?= python3` Makefile variable or ensure a `python` shim exists in dev environments.

### Metadata
- Reproducible: yes
- Related Files: Mobile Picking und Voice Assistant/Makefile

---

## [ERR-20260508-002] docker_missing_in_openclaw_runtime

**Logged**: 2026-05-08T13:00:00+02:00
**Priority**: medium
**Status**: pending
**Area**: infra

### Summary
`docker compose ps` could not run from the current OpenClaw runtime because `docker` is not installed/available in PATH.

### Error
```text
/usr/bin/sh: 1: docker: not found
Command not found
```

### Context
- Attempted to inspect whether the local n8n stack is running.
- Repo has Docker/n8n CLI rollout scripts, but this runtime cannot directly execute Docker.

### Suggested Fix
Use a host/node runtime with Docker access for live n8n import/backup/activation, or use the n8n Public API/MCP over HTTP with credentials supplied outside the repo.

### Metadata
- Reproducible: yes
- Related Files: Mobile Picking und Voice Assistant/infrastructure/scripts/import-workflows.sh

---

## [ERR-20260508-003] claude_code_review_hung

**Logged**: 2026-05-08T13:30:00+02:00
**Priority**: medium
**Status**: pending
**Area**: tooling

### Summary
A Claude Code CLI review request for VPS/n8n documentation consolidation produced no output and had to be terminated.

### Error
```text
claude --print ... stayed running without output for over 30 seconds in this OpenClaw runtime.
```

### Context
- Intended use: second-pass review before consolidating VPS deployment docs.
- No file edits were delegated to Claude.
- Codex-side consolidation proceeded conservatively.

### Suggested Fix
Use Claude Code with a shorter prompt, explicit timeout, or interactive PTY in future. Do not block straightforward repo cleanup on a hung secondary reviewer.

### Metadata
- Reproducible: unknown
- Related Files: Mobile Picking und Voice Assistant/docs/VPS_RUNBOOK.md

---
