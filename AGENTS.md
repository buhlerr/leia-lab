# Agent Instructions

leia-lab analyses Brazilian residential lease contracts ("minutas"). A file is read and masked locally, a LangGraph pipeline checks each clause against a versioned risk matrix in Postgres, and every run leaves an immutable `analyses` row plus an append-only `analysis_trail`. Users touch it through the CLI; the risk matrix is edited in a Django Admin. Domain terms: `GLOSSARY.md`. Decisions: `docs/adr/`. Production ops (homelab CT 116, backups, Cloudflare Tunnel): `docs/OPERACAO.md`.

## Layout

- `src/cli.py`: entry point (`python -m src.cli init|init --real|analyze|gold-run|gold-compare|apply-matrix|data-versions|trace-usage`).
- `src/graphs/`: LangGraph graphs (`analyze_minuta_graph`, `ingest_graph`, `query_graph`) and the pure clause rules (`minuta_rules`). `debug.py` exposes compiled graphs for visual debuggers.
- `src/ingest/masking.py`: the privacy boundary. Raw text and real filenames never enter a graph, a row or a trace.
- `src/db/`: asyncpg access, schema, seed and data versions. `src/rag/`: embeddings and hybrid search. `src/eval/gold.py`: gold-set scoring. `src/clients/`: OpenRouter LLM and Jev (TypeSafe) clients, with offline fallbacks when the key is empty.
- `src/api/`: FastAPI HTTP API for the separate front-end: `python -m src.api` (uvicorn on `0.0.0.0:${PORT:-8080}`, bearer `LEIA_API_TOKEN`, OpenAPI contract at `/docs`). Pure core in `service.py`; uploads (.pdf/.docx/.txt) are masked in `prepare_input` before any external call, and the real filename never leaves the process.
- `src/management/`: Django Admin (`leia_admin` project, `domain` app with `domain_history` audit).
- `data/`: versioned base normativa and risk matrix. `gold/`: gold set. `deploy/`: production image, backup and firewall.
- Git-ignored, local only, never commit or upload: `leia-minutas-teste-mascaradas/` (test minutas, `LEIA_MINUTAS_DIR`), `leia-kb-legislacao/` (a separate repo with raw legislation sources), `.local/` (CLI runs and verification evidence), `.planning/`.

## Where things run

Production lives in the homelab, container CT 116. Look there, not in a local checkout. The service inventory — admin, API, MLflow, LangSmith, production Postgres, backups, secrets, and how to reach each — lives in one place: `docs/OPERACAO.md`. When something moves, update it there; every other doc points to it, none keeps a second copy.

**Windows** (`C:\Users\Vitor\dev\leia-lab`) is on the home LAN and holds the test minutas. Run commands in Git Bash.

**VPS** (`/data/projects/leia-lab`, host `acfs`) reaches the homelab only through Tailscale: `ssh pve` is the `~/.ssh/config` alias (key `~/.ssh/leia_pve`), then `pct exec 116`. Never go at the homelab by its LAN IPs: the routes and why they fail live in one place, `docs/OPERACAO.md`; use the `ssh pve` path. The 1Password CLI `op` is installed in `~/.local/bin` with a read-only service account; run `export OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/leia-lab.token)"` before `op run`. The test minutas are here too (`leia-minutas-teste-mascaradas/`, git-ignored, `LEIA_MINUTAS_DIR`). The VPS Postgres on `localhost:5433` holds only test and `leia_lab_verify_*` databases, never production data.

## Build and test

Windows, Python 3.12+ in `.venv` managed by uv. Run commands from the repo root in Git Bash.

```bash
uv sync                                   # install
scripts/ci.sh                             # every check (pytest + Django + TLA+ model); needs Postgres (TEST_DATABASE_URL, default localhost:5433/leia_lab_test) and java 11+
docker compose up -d postgres             # local Postgres 17 + pgvector on 5433, if the homelab one is not used
```

`scripts/ci.sh` is the CI: DSR runs it (`required_checks: ["scripts/ci.sh"]` in its registry). A new kind of check goes in as a `step` there, never as a command only a doc mentions. Changing how an analysis starts, fails or finishes: run the `verify-analysis-lifecycle` skill (`.claude/skills/verify-analysis-lifecycle/`).

The suite drops and recreates `public` in the test database; `tests/_db_guard.py` refuses any database not ending in `_test`. To prove a change end to end, use the `verify-leia-lab` skill (`.claude/skills/verify-leia-lab/`), not bare `python -m src.cli`: it pins a disposable `leia_lab_verify_<id>` database and blanks paid keys.

Secrets come from 1Password (`op run --env-file=.env.op -- <cmd>`, in Git Bash on Windows). Never write secret values to disk. Paid paths (real OpenRouter/TypeSafe keys, `--trace`) spend money; ask first.

## Git

This repository opts in to the **Team-maintainer** profile of the Beads block below, with one limit: the owner merges into `master`.

- Work on a feature branch off `master` (`feat/…`, `fix/…`, `docs/…`). Commit small verified units on it, push it, and open a PR to `master` without asking.
- Never merge into `master`, push to `master`, or force-push a branch someone else pushed to. The owner reviews and merges every PR.
- Ask first for anything irreversible or paid: deploys to CT 116, writes to production Postgres, real OpenRouter/TypeSafe keys, `--trace`.
- A "do not commit" or "do not push" in the current request still wins.
- At session start (after `bd dolt pull`) and at session close (before `bd dolt push`), sync Beads with Linear (team `VIT`): `op run --env-file=.env.op -- scripts/linear-sync.sh`. It pulls everything from Linear, pushes open beads, and pushes closed beads already in Linear. Never run a bare `bd linear sync`: it would push the closed history.

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
