---
name: pstack-cp-interrogate
description: Adversarially inspect assumptions, edge cases, and failure modes with structured findings.
---

# Procedure: Interrogate (Adversarial Verification)

Challenge happy-path assumptions and verify edge cases, error paths, and concurrency boundaries.

## Steps

1. Inspect the active unit and checklist with `pstack-cp orch pickup <unit_id> --json`.
2. Delegate targeted adversarial checks via `Agent (general-purpose)` when inspecting multiple modules.
3. Run `pstack-cp orch verify <unit_id> --lens interrogate --scope "<scope>" --findings-json '<json>'` with explicit `blocker`, `major`, or `nit` findings.
4. Escalate irreversible risk remediation only via `AskUserQuestion`.
