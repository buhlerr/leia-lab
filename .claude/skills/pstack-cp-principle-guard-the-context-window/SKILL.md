---
name: principle-guard-the-context-window
description: "Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads."
disable-model-invocation: true
---

# Guard the Context Window

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.

**Pattern:**
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.
## Control Plane Integration (`pstack-cp`)

- Delegate subagent work via: `Agent (general-purpose)`
- Escalate irreversible human gates via: `AskUserQuestion`
- Record ledger units, steps, pauses, and evidence via: `pstack-cp orch`
- Verify claims against the live Git state via: `pstack-cp orch verify`
