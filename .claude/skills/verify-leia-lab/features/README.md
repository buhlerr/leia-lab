# leia-lab verification map

This directory is the maintained source for verifying the user-facing behavior of leia-lab. Read this index before driving the app, then use the matching feature file as the recipe. All commands assume Git Bash at the repo root and `V=".venv/Scripts/python.exe .claude/skills/verify-leia-lab/scripts/verify.py"` (see `../SKILL.md`).

## Baseline preconditions

- A run id of your own, e.g. `r1`, used for every command of the run.
- `$V launch --run-id r1` (default seed: 6 risks, 1 minuta type, 10 themes) or `$V launch --run-id r1 --real` (base normativa v1 with 330 articles, matriz v1 with 185 active risks). Each feature says which one it needs.
- `$V doctor --run-id r1` exits 0 and shows the expected `active_risks` and `kb_docs`.
- Masked test minutas in `leia-minutas-teste-mascaradas/` (`locacao-01.txt` … `locacao-06.txt`, git-ignored, local only).
- Never drive the production `leia_lab` database or an admin you did not start.

## Driving conventions

- CLI actions go through `$V cli --run-id r1 -- <src.cli args>`, never bare `python -m src.cli`.
- State checks go through `$V sql --run-id r1 --label <what> "<SELECT>"`.
- Admin saves go through `$V admin-edit`; read-only admin pages through curl with the cookie recipe in `../SKILL.md`.
- Treat every command as literal. Keep quoted names and flags unchanged.
- Gold-run labels start with the run id (`r1-a`, `r1-b`) so cleanup can move them out of `.local/gold-runs/`.

## Proof and skip reporting

- Capture the user action and the resulting state: a CLI transcript plus a `sql` read of the row it wrote.
- Admin proof is the `admin-edit` JSON (`saved: true`, final URL is the changelist) plus the `domain_history` row it produced.
- Offline is the only mode here. Report gold scores as mechanism checks, never as quality.
- Report an unreachable path with the attempted command and the unmet precondition (for example, `doctor` `server_error`).
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with verify.py` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

## Features

- [Analyze a minuta](./analyze.md) covers `analyze`, the `analyses` row, the audit trail and the filename alias.
- [Data versions](./data-versions.md) covers `init --real`, `apply-matrix` and `data-versions`.
- [Gold evaluation](./gold-evaluation.md) covers `gold-run` and `gold-compare`, including severity scoring.
- [Privacy boundary](./privacy.md) covers masking, filename alias and the graphs' refusal of raw text, offline and without a database.
- [Admin rule editing](./admin-rules.md) covers login, the domain changelists, saving a risk and the `domain_history` audit.

Not mapped yet: `trace-usage` and `--trace` (need LangSmith/MLflow credentials through Shelve and spend plan quota), knowledge-base upload in the admin (`KbDoc`), and the read-only admin views of analyses and trail.
