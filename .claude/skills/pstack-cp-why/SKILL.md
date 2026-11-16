---
name: pstack-cp-why
description: Clarify intent, constraints, and falsification criteria before committing to implementation.
---

# Procedure: Why (Intent & Constraints)

Ensure the problem statement, non-goals, and acceptance criteria are unambiguous before expanding scope.

## Steps

1. Check existing unit state and standing orders using `pstack-cp orch unit list --json`.
2. Gather codebase evidence first; delegate deep read-only investigation via `Agent (general-purpose)` when needed.
3. Ask the operator only when a truly blocking ambiguity or irreversible trade-off exists, using `AskUserQuestion`.
4. Record the clarified scope and verify assumptions with `pstack-cp orch verify <unit_id> --lens interrogate --scope "<scope>" --findings-json '[]'`.
