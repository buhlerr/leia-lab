---
name: pstack-cp-blast-radius
description: Map callers, downstream dependencies, and side-effects affected by a change.
---

# Procedure: Blast Radius (Impact Analysis)

Trace every caller, schema consumer, and cross-worktree side-effect touched by the current diff.

## Steps

1. Query unit dependencies and recent runs with `pstack-cp orch unit list --json`.
2. Delegate wide dependency searches via `Agent (general-purpose)` if the surface area spans multiple packages.
3. Record impact findings against the live Git state using `pstack-cp orch verify <unit_id> --lens blast-radius --scope "<scope>" --findings-json '<json>'`.
4. If the change requires an irreversible migration or destructive cleanup, request approval through `AskUserQuestion`.
