---
name: pstack-cp-arena
description: Compare candidate implementations or branches and record a manual ComparisonRecord in the ledger.
---

# Procedure: Arena (Candidate Comparison)

Compare alternative approaches side by side and persist an auditable `ComparisonRecord` in the V1 ledger.

## Steps

1. Evaluate candidate branches or patches independently; delegate parallel analysis via `Agent (general-purpose)`.
2. Verify each candidate's behavior using `pstack-cp orch verify <unit_id> --lens test -- <cmd...>`.
3. Record the comparison in the ledger:
   `pstack-cp orch compare <unit_id> --title "<title>" --candidate "<name>:<ref>:<summary>" --chosen "<name>" --rationale "<why>" --json`.
4. Request human approval via `AskUserQuestion` only if promoting the winner involves an irreversible action (e.g., force push or production deploy).
