# Task Completion

- Always start with and preserve dirty-worktree awareness: do not revert unrelated user changes.
- Backend changes: run `make verify-code` (`make test`) from `Mobile Picking und Voice Assistant/`.
- PWA or UI-spec changes: run `make verify-ui`; for visible UI changes also run `make verify-visual`, `make verify-visual-diff`, and `make verify-a11y`.
- n8n workflow or backend webhook contract changes: run `make verify-workflows`.
- If local Docker stack is already running or stack behavior changed, run `make verify-stack`.
- Full completion path when feasible: `make verify`.
- After Serena onboarding/memory edits, user can run `serena memories check` from project root to validate memory references.