---
name: verify-leia-lab
description: Drive the real leia-lab app and capture proof. Primary surface is the CLI (`python -m src.cli`: init, analyze, gold-run/gold-compare, apply-matrix, data-versions); secondary is the Django Admin (`src.management.manage runserver`) that edits the risk matrix with `domain_history` audit. Use when you need to prove a change to analysis graphs, matrix/base data versions, gold scoring, or the admin actually works end to end against a disposable Postgres database, not just in pytest.
---

# Verify leia-lab

leia-lab analyses Brazilian lease contracts ("minutas"): a masked text goes through a LangGraph pipeline that reads the risk matrix from Postgres and writes an auditable `analyses` row plus an `analysis_trail`. Users touch it through the CLI and, for editing rules, the Django Admin. There is no other UI.

Everything goes through one helper, run from the repo root (`C:\Users\Vitor\dev\leia-lab`) in **Git Bash**:

```bash
V=".venv/Scripts/python.exe .claude/skills/verify-leia-lab/scripts/verify.py"
```

Pick a run id (`[a-z0-9_]`, e.g. `r1`). Each run owns the database `leia_lab_verify_<run_id>` and the evidence folder `.local/verify-proof/<run_id>/`. Two runs with different ids never share state; never reuse a run id another agent is using.

## Launch

The database server is picked automatically:

1. `VERIFY_PG_SERVER` if set (e.g. `postgresql://leia:leia_lab_2026@localhost:5433` for the docker-compose Postgres).
2. Otherwise the homelab Postgres (CT 116, user `leia`; the address is inventory, kept in `docs/OPERACAO.md` — the helper has it) when the Windows user variable `LEIA_HOMELAB_PG_PASSWORD` is set. This is the usual case: local Docker is normally stopped. The same server hosts the production `leia_lab` and Directus, so the helper only ever creates and drops `leia_lab_verify_*`.
3. Otherwise `localhost:5433` (start it with `docker compose up -d postgres`).

```bash
$V launch --run-id r1           # schema + default seed (6 risks, 1 type). ~6 s
$V launch --run-id r1 --real    # + base normativa v1 (330 articles) + matriz v1 (185 risks). Needed for gold.
```

`launch` creates the database and then runs the real `python -m src.cli init [--real]` against it. Ready means it printed `READY database=leia_lab_verify_r1` and exited 0. `init` is idempotent, so you can re-run `launch` on the same id.

The admin is optional and only needed for admin features:

```bash
$V admin-up --run-id r1 --port 8011
```

It runs `migrate`, creates the superuser `verify` / `verify-pass-2026`, starts `runserver 127.0.0.1:8011 --noreload` in the background, records its PID in the evidence folder, and is ready when it prints `ADMIN_READY http://127.0.0.1:8011/admin/ ...` (it polls `/ping/` for `{"ok": true}`). Use a different `--port` per concurrent run.

Teardown is `$V cleanup --run-id r1` (see Cleanup).

## Doctor

Run this first, and again whenever anything looks off. Read-only.

```bash
$V doctor --run-id r1
```

It prints JSON with the server (password redacted), Postgres version, `git_head`, whether the database exists, table count (10 after `init`), `active_risks` (6 with the default seed, 185 after `--real`, 184 after matrix v2/v3), `kb_docs` (0 or 330), `data_versions`, `analyses` count, and the admin PID/port with its `/ping/` status. Exit 1 plus a `hint` means it is not worth driving yet. `server_error` means the Postgres server is unreachable: check `LEIA_HOMELAB_PG_PASSWORD` / VPN-LAN, or start Docker.

## Drive

Pick the feature from [features/README.md](features/README.md). The three driving verbs:

```bash
$V cli --run-id r1 -- analyze leia-minutas-teste-mascaradas/locacao-01.txt   # any src.cli command
$V sql --run-id r1 --label after-analyze "SELECT id, status FROM analyses"    # read-only SELECT
$V admin-edit --run-id r1 --path admin/domain/riskmatrix/1/change/ --set criticality=amarelo
```

- `cli` runs `python -m src.cli <args>` with `DATABASE_URL` pinned to the run's database, `OPENROUTER_API_KEY` and `TYPESAFE_API_KEY` blanked (offline LLM, offline hash embeddings, offline Jev stub), `LANGSMITH_TRACING=false`, and `LEIA_MINUTAS_DIR=leia-minutas-teste-mascaradas`. It echoes stdout/stderr and writes a transcript. Never run `python -m src.cli` directly for verification: without the helper it falls back to whatever `DATABASE_URL` the shell has.
- `sql` runs one statement inside a read-only transaction, so it cannot mutate anything. Use it to prove side effects.
- `admin-edit` logs in as `verify`, GETs the admin change form, keeps every current value, overrides the `--set` fields, and POSTs with `_save`, exactly like a user pressing Salvar. It fails (exit 1) on validation errors or an unknown field name and lists the valid fields. Write the path without the leading slash: Git Bash rewrites `/admin/...` into a Windows path (the helper also repairs that).

To check the privacy boundary without any database (works when Postgres is down): `$V privacy --run-id p1`, see [features/privacy.md](features/privacy.md).

For read-only admin pages, curl works:

```bash
J=$(mktemp); curl -s -c $J -b $J -o /dev/null "http://127.0.0.1:8011/admin/login/?next=/admin/"
T=$(grep csrftoken $J | awk '{print $7}')
curl -s -c $J -b $J -o /dev/null -w "%{http_code}\n" -e "http://127.0.0.1:8011/admin/login/" \
  -d "csrfmiddlewaretoken=$T&username=verify&password=verify-pass-2026" "http://127.0.0.1:8011/admin/login/?next=/admin/"
curl -s -b $J http://127.0.0.1:8011/admin/domain/riskmatrix/ | grep -o 'href="/admin/domain/riskmatrix/[0-9]*/change/"'
```

Paid paths (real OpenRouter / TypeSafe keys, `--trace` to LangSmith/MLflow, `trace-usage`) are out of scope for this skill. They need `op run --env-file=.env.op -- ...` and spend money or plan quota; ask the user first.

## Evidence

Everything lands in `.local/verify-proof/<run_id>/` (git-ignored), numbered in order: `01-launch-init.txt`, `02-cli-analyze-....txt`, `03-sql-<label>.json`, `NN-admin-edit-....json`, `admin-server.log`, and after cleanup `gold-runs/`. Transcripts start with the command, database, exit code and duration; DSN passwords are redacted.

Proof standards:

- Drive the real entry points (`src.cli` commands, admin forms over HTTP). Never call graph functions, models or setters from Python to "prove" a feature.
- Capture the action and the resulting state: a CLI transcript is not enough on its own. Follow it with a `sql` query that shows the row it wrote (`analyses`, `analysis_trail`, `domain_history`, `data_versions`, `kb_docs`).
- Check the privacy invariant whenever a minuta is involved: `analyses.filename_alias` is `documento-<sha8>.<ext>` and the real filename or unmasked personal data never appears in `analyses`, `analysis_trail` or `kb_docs`.
- Offline mode is the only mode here, and it is a real production boundary (no key means offline clients), not a mock. Offline scores prove the mechanism only: the Jev stub answers `noul=0.75` and always picks the first theme, so `analyze` raises the same `R-04` alert for every minuta and gold scores are not quality numbers. Never report an offline gold F1 as a quality result.

## Cleanup

```bash
$V cleanup --run-id r1
```

It stops the admin server this run started (by the recorded PID, `taskkill /T`), moves `.local/gold-runs/<run_id>-*.json` into the evidence folder, terminates connections to `leia_lab_verify_r1` and drops it (it refuses any name without that prefix). Evidence stays. `admin-down --run-id r1` stops only the admin. Never kill `python.exe` by name: the user may have their own runserver or CLI running. Run cleanup after failed attempts too, so no database is left on the shared homelab server. Leftovers from earlier runs show up as `SELECT datname FROM pg_database WHERE datname LIKE 'leia_lab_verify_%'` (run via `$V sql` from any live run).

## Helpers

`.claude/skills/verify-leia-lab/scripts/verify.py` (stdlib + the repo's `.venv`, which has asyncpg). Always invoke it with `.venv/Scripts/python.exe`. Subcommands, all taking `--run-id ID`:

| Subcommand | Does |
|---|---|
| `launch [--real]` | create `leia_lab_verify_<ID>`, run `src.cli init [--real]` |
| `doctor` | read-only health of server, database, schema, data, admin |
| `cli -- <args>` | `src.cli <args>` against the run's database, transcript saved |
| `privacy` | offline masking/alias/raw-text-refusal probe, no database needed |
| `sql "<SELECT>" [--label L]` | read-only query, JSON saved |
| `admin-up [--port 8011]` | migrate, superuser `verify`, runserver in background |
| `admin-edit --path P --set F=V ...` | log in and save an admin change form |
| `admin-down` | stop this run's admin |
| `cleanup` | admin-down, move gold-run labels, drop the database; evidence kept |
