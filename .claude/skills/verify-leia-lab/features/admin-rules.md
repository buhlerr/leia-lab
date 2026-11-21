# Admin rule editing

An editor signs in to the Django Admin and edits the rules the analysis reads: minuta types, themes, the risk matrix and prompts. Every save is recorded by a database trigger in the append-only `domain_history` (old row, new row, database user). History, analyses and trail are visible but read-only for everyone, superuser included.

## Sub-features

- `admin-ping` `/ping/` answers `{"ok": true}`; `/` redirects to `/admin/`.
- `admin-login` the login form accepts the user and lands on the admin index.
- `admin-index` `/admin/domain/` lists analysis, analysistrail, domainhistory, kbchunk, kbdoc, minutatype, prompt, riskmatrix, theme.
- `admin-edit-risk` saving a risk change form updates `risk_matrix` and adds a `domain_history` UPDATE row.
- `admin-readonly` history, analyses and trail cannot be edited or deleted.

## How to get to it (user POV)

- Browser at `http://127.0.0.1:<port>/admin/` (production: https://admin.rauvbr.com behind Pangolin SSO, never driven by this skill).
- Domain sections: Domain → Risk matrix / Themes / Minuta types / Prompts; each row has a change form with a Salvar button.

## Driving it with verify.py

Preconditions:

- `$V launch --run-id r1` done (default seed: risk id 1 is `R-01`, `vermelho`).
- `$V admin-up --run-id r1 --port 8011` printed `ADMIN_READY`.

- **Health.** `curl -s http://127.0.0.1:8011/ping/` prints `{"ok": true}`; `curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" http://127.0.0.1:8011/` prints `302 http://127.0.0.1:8011/admin/`.
- **Login and index.** Use the curl cookie recipe in `../SKILL.md`; the login POST returns 302 and `curl -s -b $J http://127.0.0.1:8011/admin/domain/ | grep -o 'href="/admin/domain/[a-z]*/"' | sort -u` lists the nine sections above.
- **Read before.** `$V sql --run-id r1 --label risk1-before "SELECT id, risk_id, criticality FROM risk_matrix WHERE id=1"`. `R-01`, `vermelho`.
- **Save a risk.** `$V admin-edit --run-id r1 --path admin/domain/riskmatrix/1/change/ --set criticality=amarelo`. JSON with `"before": {"criticality": "vermelho"}`, `"final_url": "/admin/domain/riskmatrix/"`, `"saved": true`, no errors.
- **Confirm the audit.** `$V sql --run-id r1 --label risk1-history "SELECT r.criticality AS now, h.op, h.db_user, h.old_row->>'criticality' AS old, h.new_row->>'criticality' AS new FROM risk_matrix r JOIN domain_history h ON h.row_id=r.id AND h.table_name='risk_matrix' WHERE r.id=1 ORDER BY h.id DESC LIMIT 1"`. `now` amarelo, `op` UPDATE, `old` vermelho, `new` amarelo.
- **Read-only history.** `curl -s -b $J -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/admin/domain/domainhistory/add/` is 403.
- **Proof.** `NN-admin-edit-...json`, both SQL JSONs, `admin-server.log`.

## Gotchas

- `db_user` is `leia` here because the verification admin connects as the schema owner; in production it is `django_login`. Do not assert `django_login` locally.
- Saving a form with no real change writes no history row (the trigger skips identical rows). Pick a value different from `before`.
- The criticality choices are `vermelho`, `amarelo`, `verde` (Portuguese), not red/yellow/green; the CLI and gold use red/yellow/green.
- Write `--path` without the leading slash in Git Bash, or it turns into `C:/Program Files/Git/admin/...`.
- One admin per run id; a second `admin-up` refuses until `admin-down`.
