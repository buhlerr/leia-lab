---
name: pstack-cp-how
description: Decompose work into concrete units, playbook checklists, and DAG dependencies in the orch ledger.
---

# Procedure: How (Planning & Decomposition)

Translate an approved goal into concrete, verifiable units in the `pstack-cp orch` ledger before editing files.

## Steps

1. Create each unit with an explicit playbook: `pstack-cp orch unit create --title "<title>" --playbook <id> --json`.
2. Wire ordering constraints with `pstack-cp orch unit dep <unit_id> --on <depends_on_id> --json` (cycles are rejected).
3. Attach standing orders (`--standing-order "<rule>"`) so constraints survive `pause` / `pickup`.
4. Delegate independent exploration or parallel unit implementation via `Agent (general-purpose)`.
5. Validate every unit's completion criteria with `pstack-cp orch verify <unit_id> --lens test -- <cmd...>` and escalate irreversible changes through `AskUserQuestion`.
