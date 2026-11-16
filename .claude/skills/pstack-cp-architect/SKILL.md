---
name: pstack-cp-architect
description: Evaluate system boundaries, data integrity, concurrency, and failure modes before coding.
---

# Procedure: Architect (Design & Trade-offs)

Design minimal, cohesive interfaces that respect Windows process/file semantics and single-source-of-truth persistence.

## Steps

1. Inspect existing module contracts and register architectural units in `pstack-cp orch`.
2. Subtract unnecessary layers (`subtract-before-you-add`) and prefer reusing existing primitives.
3. Delegate focused codebase boundary checks through `Agent (general-purpose)`.
4. Record architectural review findings with `pstack-cp orch verify <unit_id> --lens architect --scope "<scope>" --findings-json '<json>'`.
5. Gate irreversible schema drops, destructive migrations, or external publishing via `AskUserQuestion`.
