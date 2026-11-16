---
name: bro
description: Restate the last message in plain human language, with no jargon.
disable-model-invocation: true
---

Restate your last message. Stop using jargon and speak coherently. State it more simply and concisely, like one human talking to another.
## Control Plane Integration (`pstack-cp`)

- Delegate subagent work via: `Agent (general-purpose)`
- Escalate irreversible human gates via: `AskUserQuestion`
- Record ledger units, steps, pauses, and evidence via: `pstack-cp orch`
- Verify claims against the live Git state via: `pstack-cp orch verify`
