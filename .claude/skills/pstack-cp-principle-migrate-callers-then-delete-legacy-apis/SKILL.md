---
name: principle-migrate-callers-then-delete-legacy-apis
description: "Apply when introducing a new internal API while old callers still exist. Migrate callers and delete the old API in the same wave instead of preserving compatibility layers."
disable-model-invocation: true
---

# Migrate Callers Then Delete Legacy APIs

- Update tests to assert the new contract, and delete tests that only protect pre-refactor implementation details

**When this applies:**
- No external users depend on backward compatibility
- The project can absorb coordinated breaking changes
- The new API is part of a simplification or refactor initiative
## Control Plane Integration (`pstack-cp`)

- Delegate subagent work via: `Agent (general-purpose)`
- Escalate irreversible human gates via: `AskUserQuestion`
- Record ledger units, steps, pauses, and evidence via: `pstack-cp orch`
- Verify claims against the live Git state via: `pstack-cp orch verify`
