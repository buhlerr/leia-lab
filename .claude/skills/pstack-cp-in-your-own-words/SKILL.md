---
name: in-your-own-words
description: "Restate in your own words what you think the user's goals are and what problem they're trying to solve. Use for /in-your-own-words."
disable-model-invocation: true
---

Restate in your own words what you think the user's goals are and what problem they're trying to solve.
## Control Plane Integration (`pstack-cp`)

- Delegate subagent work via: `Agent (general-purpose)`
- Escalate irreversible human gates via: `AskUserQuestion`
- Record ledger units, steps, pauses, and evidence via: `pstack-cp orch`
- Verify claims against the live Git state via: `pstack-cp orch verify`
