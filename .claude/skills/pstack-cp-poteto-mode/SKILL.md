---
name: pstack-cp-poteto-mode
description: Default pstack adaptive engineering orchestrator backed by the pstack-cp orch ledger.
---

# Poteto Mode (`pstack-cp`)

Coordinate engineering units from backlog to verified completion while keeping reversible progress moving (`Never Block on the Human`) and binding every verification to live Git state (`Green ≠ Safe`).

## Core Protocol

1. Inspect active units and pickup context via `pstack-cp orch unit list --json` and `pstack-cp orch pickup <unit_id> --json`.
2. Advance reversible playbook steps continuously and mark progress with `pstack-cp orch step check <unit_id> <step_index> --status done --json`.
3. Delegate isolated subtasks when helpful using `Agent (general-purpose)`.
4. Never fabricate `VERIFIED` verdicts: run deterministic commands via `pstack-cp orch verify <unit_id> --lens test -- <cmd...>` and qualitative lenses with structured `--findings-json`.
5. Pause for human input ONLY on irreversible operations using `AskUserQuestion` or `pstack-cp orch gate request <unit_id> --action <kind> --summary <text> --reason <text> --json`.

## Playbook Catalog Reference

### Principles

- **never-block-on-the-human**: Keep reversible engineering steps moving continuously; pause for human approval only on irreversible actions via gates.
- **green-neq-safe**: Passing checks are necessary but not sufficient; bind every VERIFIED verdict to the live Git state fingerprint and re-evaluate freshness after edits.
- **laziness-protocol**: Do not invent speculative scope or skip verification of assumptions; inspect existing code and constraints first.
- **subtract-before-you-add**: Prefer removing dead complexity or reusing existing modules over adding new abstractions.
- **prove-it-works**: Demonstrate behavior with reproducible commands, edge-case checks, and explicit findings rather than assertions.

### Built-in Playbooks

- **`poteto-mode`** (Poteto Mode): Default adaptive engineering orchestrator routing work through units, checklists, and evidence gates.
  1. Clarify intent and constraints if truly ambiguous [procedure: `why`]
  2. Inspect existing codebase and plan unit breakdown [procedure: `how`]
  3. Execute reversible implementation steps continuously
  4. Audit diff quality and blast radius [procedure: `unslop`]
  5. Verify with deterministic tests and qualitative lenses [procedure: `interrogate`]
- **`feature`** (Feature Delivery): End-to-end workflow for designing, implementing, and verifying a new capability.
  1. Validate requirements and acceptance criteria [procedure: `why`]
  2. Design architecture and module boundaries [procedure: `architect`]
  3. Write implementation plan and register dependent units [procedure: `how`]
  4. Implement changes incrementally with unit tests
  5. Run blast-radius and unslop review [procedure: `blast-radius`]
  6. Verify build, lint, and test suite on current Git state
- **`bug-fix`** (Bug Fix): Root-cause reproduction, minimal fix, and regression verification.
  1. Reproduce failure with an automated test or minimal command
  2. Trace root cause without speculative patches [procedure: `interrogate`]
  3. Apply targeted fix and verify regression test passes
  4. Check blast radius and clean up residual code [procedure: `blast-radius`]
- **`investigation`** (Technical Investigation): Structured research and evidence gathering without premature edits.
  1. Define hypotheses and falsification criteria [procedure: `why`]
  2. Inspect code paths, logs, and runtime behavior [procedure: `interrogate`]
  3. Document findings and recommended next units
- **`refactoring`** (Safe Refactoring): Behavior-preserving structural simplification with before/after verification.
  1. Establish baseline test coverage before modifying structure
  2. Map callers and side-effects [procedure: `blast-radius`]
  3. Refactor in small verifiable increments [procedure: `unslop`]
  4. Re-verify full test suite and typecheck
- **`perf-issue`** (Performance Issue): Baseline measurement, bottleneck isolation, and benchmarked optimization.
  1. Capture reproducible baseline latency or throughput metrics
  2. Profile hotspot and evaluate candidate approaches [procedure: `arena`]
  3. Implement winning optimization and verify correctness + benchmark
- **`hillclimb`** (Hillclimb): Iterative metric-driven optimization loop with strict regression guards.
  1. Define scalar objective metric and invariant tests
  2. Run candidate experiments and record ComparisonRecord [procedure: `arena`]
  3. Keep only verified improvements and discard regressions
- **`orchestrate`** (Multi-Unit Orchestration): Coordinate dependent units across workers using DAG dependencies and leases.
  1. Decompose work into units with explicit unit_deps DAG [procedure: `how`]
  2. Dispatch independent units to wrapped workers or subagents
  3. Validate cross-unit integration and fresh evidence [procedure: `blast-radius`]
- **`shipping-prep`** (Shipping Prep): Pre-release quality audit, diff hygiene, and irreversible gate preparation.
  1. Audit full diff for leftover debug code or unintended edits [procedure: `unslop`]
  2. Run final deterministic verification on clean Git state
  3. Request human gate for any irreversible release or merge action
