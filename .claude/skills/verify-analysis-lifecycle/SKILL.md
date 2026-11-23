---
name: verify-analysis-lifecycle
description: Model-check (TLA+/TLC) the lifecycle of an `analyses` row in leia-lab: analyze() owns the row from INSERT to a final status, so no run ends with the row stuck in 'running', a finished status never changes, a finished row's trail starts with `iniciar`, and one idempotency key names at most one row. Use when a change touches analyze()/analyze_stream(), the iniciar or validar nodes, src/db/analyses.py, or the analyses table/trigger in src/db/schema.sql, or when you add an await, a node, or an error handler on that path.
---

# Verify the analysis lifecycle

## What is verified

- **NoRunEndsRunning.** Once `analyze()` returns or raises, its `analyses` row is not `running`. Harm if broken: the admin and the API show an analysis "em andamento" forever, and nobody knows it died (the PR #31 review finding).
- **TerminalNeverChanges.** `done`, `unsupported` and `failed` never change. Harm: a finished, audited result is rewritten after the fact, e.g. a `done` report overwritten by `failed`.
- **TrailStartsWithIniciar.** A finished row has the `iniciar` entry first in `analysis_trail`. Harm: a row nobody can reconstruct (no rules hash, no params).
- **ReturnedMeansFinished.** `analyze()` returns normally only after the row reached `done` or `unsupported`.
- **OneRowPerKey.** A run whose `Idempotency-Key` another call already holds writes no row and no trail, and raises `AnalysisKeyTaken` before any external call. Harm if broken: a retried POST runs the paid calls again and leaves a second undeletable row and trail (VIT-8).

The model is [model/AnalysisLifecycle.tla](model/AnalysisLifecycle.tla). TLC explores every order of success, exception and cancellation (`asyncio.CancelledError`) at every await point of one `analyze()` call, and for DB writes both "failed before commit" and "committed, then the reply was lost".

## Run it

From the repo root (Git Bash on Windows, bash elsewhere). Needs `java` 11+ on `PATH` or `JAVA_HOME`; the script downloads `tla2tools.jar` v1.7.4 once into `~/.cache/leia-lab/`, checked by sha256.

```bash
bash .claude/skills/verify-analysis-lifecycle/scripts/check.sh            # ~10 s, also a step of scripts/ci.sh
bash .claude/skills/verify-analysis-lifecycle/scripts/check.sh current    # replay the PR #31 bug: full TLC trace
```

`check.sh` passes only if `fixed` passes and every other config fails on its own property:

| config | design | expected |
|---|---|---|
| `fixed` | the code as it is now | pass |
| `current` | code before the fix (`guarded()` per node) | `NoRunEndsRunning`: INSERT commits, the next step raises or is cancelled, nothing marks the row |
| `current_terminal` | same | `TerminalNeverChanges`: `finish_analysis` commits `done`, its reply is lost, `guarded()` writes `failed` over it |
| `fixed_catches_exception_only` | handler catches `Exception`, not `BaseException` | `NoRunEndsRunning` (a cancel slips through) |
| `fixed_split_iniciar` | INSERT and iniciar trail in two transactions | `TrailStartsWithIniciar` |
| `fixed_unguarded_failure` | failure UPDATE without `status = 'running'` and trigger without the freeze | `TerminalNeverChanges` |
| `fixed_no_defer` | a 2nd cancellation during the failure write ends `analyze()` first | `NoRunEndsRunning` |
| `fixed_no_unique_key` | the code before VIT-8: no unique `idempotency_key`, the INSERT always writes | `OneRowPerKey` |

Read every TLC result with the pstack `/statechart` skill: a violation becomes its shortest path in plain words, and a pass becomes a chart of the states. The `event` variable in each trace state names the code step, e.g. `start_analysis: INSERT: committed, then raised (not caught)`.

## Coverage record

Sync commit: `60fc4cd0f6897b7059d157a06f40a63df8f5662a`. At that commit the `fixed` design was checked line by line against this code:

| model | code |
|---|---|
| `Prefix`: `prepare_input`, then `own` | `analyze()` / `analyze_stream()` and `_owned_analysis` in `src/graphs/analyze_minuta_graph.py` (id made before `try`) |
| `Iniciar`: mask and id check, `load_rules_snapshot`, `insert_iniciar`, `tag_analysis` | `iniciar` node; `start_analysis` in `src/db/analyses.py` (one transaction) |
| `Node(n)`: LangGraph between nodes, external call, `append_trail` | `classificar`, `ficha`, `triar`, `buscar`, `analisar` nodes; `append_trail` |
| `Validar`: `validate_and_format`, `append_trail`, `finish_analysis` | `validar` node; `finish_analysis` |
| `Catches`, `MarkFailed` with `GuardedFailure` | `except BaseException` + `asyncio.shield(fail_analysis(...))`; `fail_analysis` `WHERE status = 'running'` |
| `TriggerFreezesTerminal`, `Statuses` | `analyses_guard()` and `analyses_status_check` in `src/db/schema.sql` |
| `other`, `OtherRunInserts`, `KeyConflict`, `UniqueKey` | another POST with the same key; `analyses_idempotency_key` unique index; `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` and `AnalysisKeyTaken` in `start_analysis` |

Did the covered code change since the sync commit?

```bash
git diff --stat 60fc4cd0f6897b7059d157a06f40a63df8f5662a -- src/graphs/analyze_minuta_graph.py src/db/analyses.py src/db/schema.sql
```

If it did, reread the changed parts against the table. Move the sync commit forward (edit this file) only after you confirm the `fixed` design still describes the code at the new commit.

## Changing the code

1. Map the change onto the model. A new `await` on the path is a new entry in `Program`; a node is a `Node(...)`; a DB write is a `DbWrites` kind with its effect in `Apply`; plain code that can raise is a `Sync`. Parallel calls under one `asyncio.gather` are one await.
2. Run `check.sh`. If `fixed` now fails, read the trace with `/statechart` and decide:
   - **Real bug:** the trace is a sequence the code can really run (every step points to a line). Fix the code, not the model.
   - **Modeling error:** a step in the trace does not exist in the code, or two steps that the code runs as one atomic step (one SQL statement, one transaction) are split. Fix the model so each entry is exactly one await or one plain block.
3. Never weaken a property to make `fixed` pass. If a broken variant stops failing, the model lost the ability to see that bug: restore it.
4. The same guarantees are tested on a real Postgres in `tests/test_trail_privacy.py` (`test_a_failure_right_after_the_insert_marks_the_analysis_failed`, `test_a_cancelled_analysis_ends_failed`, `test_a_failing_step_marks_the_analysis_failed_with_the_error_type_only`) and `tests/test_domain_schema.py` (`test_a_finished_analysis_is_frozen`, `test_analysis_status_outside_the_lifecycle_is_rejected`, `test_init_adds_the_status_check_to_an_existing_database`).

## Scope and assumptions

- One `analyze()` call and its own row. Runs never share a row (each makes its own uuid). The only other run modeled is one holding the same idempotency key (`other`), which may insert at any moment; its own lifecycle is not modeled.
- The failure UPDATE reaches Postgres. If the database itself is down, no design can mark the row; it stays `running` and the exception from `fail_analysis` is what `analyze()` raises.
- asyncpg's pool waits for a cancelled statement to settle before releasing the connection (`_wait_for_cancellation` in `asyncpg/pool.py`), so the model treats each SQL statement as committed or not by the time an `except` block runs.
- The shield keeps the failure write running if a second cancellation arrives (anyio cancels at every await of a cancelled scope). It does not survive the event loop shutting down mid-write.
- LangGraph's own awaits between nodes are one await point per edge. Checkpointers and streaming are not modeled separately.
- Running the compiled graph directly (`src/graphs/debug.py`, GraphLoupe) bypasses `analyze()`; `iniciar` refuses input without an `analysis_id`, and a caller who supplies one owns the row. Not covered.
