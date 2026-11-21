# Agent Instructions

leia-lab analyses Brazilian residential lease contracts ("minutas"). A file is read and masked locally, a LangGraph pipeline checks each clause against a versioned risk matrix in Postgres, and every run leaves an immutable `analyses` row plus an append-only `analysis_trail`. Users touch it through the CLI; the risk matrix is edited in a Django Admin. Domain terms: `GLOSSARY.md`. Decisions: `docs/adr/`. Production ops (homelab CT 116, backups, Pangolin): `docs/OPERACAO.md`.

## Layout

- `src/cli.py`: entry point (`python -m src.cli init|init --real|analyze|gold-run|gold-compare|apply-matrix|data-versions|trace-usage`).
- `src/graphs/`: LangGraph graphs (`analyze_minuta_graph`, `ingest_graph`, `query_graph`) and the pure clause rules (`minuta_rules`). `debug.py` exposes compiled graphs for visual debuggers.
- `src/ingest/masking.py`: the privacy boundary. Raw text and real filenames never enter a graph, a row or a trace.
- `src/db/`: asyncpg access, schema, seed and data versions. `src/rag/`: embeddings and hybrid search. `src/eval/gold.py`: gold-set scoring. `src/clients/`: OpenRouter LLM and Jev (TypeSafe) clients, with offline fallbacks when the key is empty.
- `src/management/`: Django Admin (`leia_admin` project, `domain` app with `domain_history` audit).
- `data/`: versioned base normativa and risk matrix. `gold/`: gold set. `deploy/`: production image, backup and firewall.
- Git-ignored, local only, never commit or upload: `leia-minutas-teste-mascaradas/` (test minutas, `LEIA_MINUTAS_DIR`), `leia-kb-legislacao/` (a separate repo with raw legislation sources), `.local/` (CLI runs and verification evidence), `.planning/`.

## Build and test

Windows, Python 3.12+ in `.venv` managed by uv. Run commands from the repo root in Git Bash.

```bash
uv sync                                   # install
.venv/Scripts/python.exe -m pytest        # tests; need Postgres (TEST_DATABASE_URL, default localhost:5433/leia_lab_test)
docker compose up -d postgres             # local Postgres 17 + pgvector on 5433, if the homelab one is not used
```

The suite drops and recreates `public` in the test database; `tests/_db_guard.py` refuses any database not ending in `_test`. To prove a change end to end, use the `verify-leia-lab` skill (`.claude/skills/verify-leia-lab/`), not bare `python -m src.cli`: it pins a disposable `leia_lab_verify_<id>` database and blanks paid keys.

Secrets come from Shelve (`shelve run --env production -- <cmd>` in Git Bash). Paid paths (real OpenRouter/TypeSafe keys, `--trace`) spend money; ask first.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

## Agent skills

### Issue tracker

Issues and specs live in Beads (`bd`), the same tracker described above. See `docs/agents/issue-tracker.md`.

### Triage labels

The seven default role strings (`bug`, `enhancement`, `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), applied as Beads labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` at the root, ADRs in `docs/adr/` once the first one is written. See `docs/agents/domain.md`.

### External peers

`auto`: picks the Claude or Codex adapter from the host family (CLI default model, effort `high`). See `docs/agents/cross-model.json`.
