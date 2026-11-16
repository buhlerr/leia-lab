---
name: pstack-cp-unslop
description: Audit diff for dead code, duplicated logic, leftover debug statements, and unnecessary complexity.
---

# Procedure: Unslop (Diff Hygiene & Simplification)

Ensure the final diff is minimal, cohesive, and free of speculative abstractions or leftover scaffolding.

## Steps

1. Review checklist status via `pstack-cp orch pickup <unit_id> --json`.
2. Delegate independent diff review via `Agent (general-purpose)` when helpful.
3. Remove dead code, duplicate helpers, and debug noise, then re-run deterministic checks and record `pstack-cp orch verify <unit_id> --lens unslop --scope "<scope>" --findings-json '<json>'`.
4. Gate any irreversible file deletion outside project scope via `AskUserQuestion`.
