# Prototype foundation (bead `leia-lab-1g1.9`, branch `prototype/foundation`)

> **Throwaway prototype code.** Published, never merged (code freeze, ADR-0001). It is the shared base for the
> tracing layer (B3) and the management layer (B4). `master` is untouched; this branch only adds `src/foundation/`,
> `gold/`, and changes `src/graphs/analyze_minuta_graph.py` plus its tests.

## What it adds

| Piece | Where |
|---|---|
| Domain tables + append-only history (trigger) + analyses/trail/snapshot DDL | `src/foundation/schema.sql` |
| Seed from master's `DEFAULT_*` and prompt constants; real-matrix loader (vz3) | `src/foundation/seed.py`, `defaults.py` |
| Atomic, hashed **rules snapshot** (what the graph runs on) | `src/foundation/rules.py` |
| Analysis record + trail writers | `src/foundation/trail.py` |
| Graph reading rules from the DB, writing the trail, **no raw text in state** | `src/graphs/analyze_minuta_graph.py` |
| Gold set (ids/hashes only) + scorer + two-version compare | `gold/gold_set.json`, `src/foundation/gold.py` |
| CLI | `python -m src.foundation.cli` |

## Schema (tables the infra worker must deploy)

`src/db/schema.sql` (corpus, unchanged): `kb_docs`, `kb_chunks` (+ `vector` extension).
`src/foundation/schema.sql` (idempotent, apply after the corpus schema):

| Table | Role |
|---|---|
| `minuta_types` | id, slug, name, `classifier_description`, active |
| `themes` | per type: slug, description, `norm_ids text[]` (the old `DEFAULT_TEMA_MAP`), position |
| `risk_matrix` | per theme: `risk_id`, description, `criticality` (`vermelho/amarelo/verde`), party, `norms jsonb` (`[{id, citacao, ...}]`), active |
| `prompts` | per type: `kind` (`redigir_system`, `triagem_risco`, `confirmar_risco`, `regula_norma`), position, text, model, active |
| `domain_history` | append-only log of every INSERT/UPDATE/DELETE on the four tables above (old/new row as jsonb, op, `changed_at`, `db_user`) |
| `analyses` | one row per run: masked-text hash, params (cutoffs), **`rules_snapshot` jsonb + `rules_hash`**, `matrix_version`, `prompt_version`, `domain_history_id`, status, report |
| `analysis_trail` | per step (per clause for triar/buscar): input summary (masked), decision, `score`/`cutoff`, versions, `cited_norms`, timestamps. Append-only |

Also created: role `leia_app` (NOLOGIN) with the grants below, functions `domain_history_log()` (SECURITY DEFINER),
`forbid_change()`, `analyses_guard()`.

* `leia_app`: full CRUD on the four domain tables; `SELECT` only on `domain_history`; `SELECT/INSERT/UPDATE` on
  `analyses` (the snapshot columns are frozen by trigger; no DELETE); `SELECT/INSERT` on `analysis_trail`.
  Give your management tool a login that is a member of `leia_app`, not the owner.
* History/trail are protected twice: no grants for `leia_app`, **and** triggers that raise on UPDATE/DELETE/TRUNCATE
  even for the owner/superuser (a superuser can still drop triggers; that is out of scope for a prototype).

## Run it

Prerequisites: Docker, [`uv`](https://docs.astral.sh/uv/). Postgres with pgvector on `localhost:5433`
(`docker compose up -d`, container `leia-lab-postgres`). No API keys: with no `TYPESAFE_API_KEY` /
`OPENROUTER_API_KEY` the Jev and LLM clients run in their deterministic offline mode.

```bash
uv sync
# tests (use a throwaway DB: the suite DROPs schema public in it)
TEST_DATABASE_URL=postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_f_test uv run pytest
```

### Acceptance demo: change a risk, the old analysis keeps the rule that decided it

```bash
export DATABASE_URL=postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_f_demo
export LEIA_MINUTAS_DIR=/path/to/leia-minutas-teste-mascaradas        # masked minutas, never committed
PSQL="docker exec -i leia-lab-postgres psql -U leia -d leia_lab_f_demo"

docker exec -i leia-lab-postgres psql -U leia -d postgres -c "CREATE DATABASE leia_lab_f_demo"
uv run python -m src.foundation.cli init                                   # schemas + seed from master's defaults

# 1. first analysis (the file is read and masked locally; the graph only gets masked text)
uv run python -m src.foundation.cli analyze "$LEIA_MINUTAS_DIR/locacao-02.txt"

# 2. change a risk directly in psql (no app code involved)
$PSQL -c "UPDATE risk_matrix SET criticality='vermelho', description='Renuncia antecipada a benfeitorias (v2)' WHERE risk_id='R-04'"

# 3. second analysis
uv run python -m src.foundation.cli analyze "$LEIA_MINUTAS_DIR/locacao-02.txt"

# 4. psql: each analysis is tied to the matrix version that decided it
$PSQL -c "SELECT left(id::text,8) id, matrix_version, prompt_version, domain_history_id AS watermark,
  (SELECT s->>'risco' FROM jsonb_array_elements(rules_snapshot->'types'->'locacao_residencial'->'riscos'->'benfeitorias_e_conservacao') s) AS risk_in_snapshot,
  (SELECT s->>'cor'   FROM jsonb_array_elements(rules_snapshot->'types'->'locacao_residencial'->'riscos'->'benfeitorias_e_conservacao') s) AS cor_in_snapshot,
  report->'content'->'alerts'->0->>'severity' AS severity
  FROM analyses ORDER BY started_at"
$PSQL -c "SELECT id, table_name, row_id, op, old_row->>'criticality' AS old, new_row->>'criticality' AS new, db_user, changed_at
  FROM domain_history WHERE op='UPDATE'"                                    # the psql write was captured

# 5. history and trail cannot be edited, even by the owner
$PSQL -c "DELETE FROM domain_history"                                       # ERROR: ... append-only
# 6. trail of one analysis, from its id alone
$PSQL -c "SELECT seq, step, clause_n, score, cutoff, matrix_version, cited_norms FROM analysis_trail
  WHERE analysis_id = (SELECT id FROM analyses ORDER BY started_at LIMIT 1) ORDER BY seq"
```

Expected (recorded from a real run): analysis 1 → `matrix_version 080154455eab`, snapshot risk `... necessárias`, `amarelo`,
alert `yellow`; analysis 2 → `matrix_version a0233d43a8d7`, snapshot risk `... (v2)`, `vermelho`, alert `red`;
`domain_history` has one `UPDATE amarelo → vermelho` row with `db_user = leia`; the watermarks (17, 18) bracket the change.

### Gold set: compare two matrix/prompt versions

```bash
uv run python -m src.foundation.cli gold-run --label v2        # analyse the 3 gold minutas + score
$PSQL -c "UPDATE risk_matrix SET active=false WHERE risk_id='R-04'"   # or edit a prompt / criticality
uv run python -m src.foundation.cli gold-run --label v3
uv run python -m src.foundation.cli gold-compare v2 v3         # P/R/F1 per version + clauses whose detection changed
```

`gold/gold_set.json` has 10 clauses over 3 minutas (`locacao-01/02/06`): ids, file sha256, clause number, clause sha256 and
expected risk ids only. **No minuta text.** `gold-run` refuses to run if the local files/segmentation do not match the hashes.
Labels are prototype labels by me, **not lawyer-validated**. In offline mode Jev answers a constant 0.75 and always picks the
first theme (`benfeitorias_e_conservacao`), so offline numbers only prove the mechanism (R-04 everywhere); real quality needs
`TYPESAFE_API_KEY` (masked text only).

## Design decisions (read before building on it)

1. **One immutable snapshot per analysis.** `iniciar` reads all active types/themes/risks/prompts in one `REPEATABLE READ`
   transaction; that content is both stored in `analyses.rules_snapshot` (+ sha256) and what the nodes read from
   `state["rules"]`. `matrix_version` / `prompt_version` are **content hashes** (so any write, including raw psql, changes them);
   `domain_history_id` is the history watermark at read time. They are global (all types), not per type: simple, slightly coarse.
2. **Rules are data, graph has no `DEFAULT_*`.** Classifier criteria come from `minuta_types`, theme criteria from `themes`,
   Jev instructions and the writer prompt from `prompts`. A missing prompt kind fails loudly (analysis marked `failed`, error
   type only). `build_analyze_minuta_graph(pool, settings, *, cutoffs..., checkpointer=None)`; the `riscos/temas/tema_map` kwargs are gone.
3. **Raw text never enters the graph.** `analyze()` / `prepare_input()` read the file and mask **outside** the graph; the graph
   input is `{text (masked), filename (alias)}`; `read_file`/`mascarar` nodes and the `raw_text`/`file_path` state fields are
   removed. `tests/test_foundation_privacy.py` runs with a checkpointer and a stream and fails if the known name/CPF/e-mail/file
   name appears in state, checkpoints, per-node updates, trail, snapshot or report (verified to fail if masking is skipped).
   Anything that wraps the graph for tracing must call `analyze()`, not `graph.ainvoke` with raw text.
4. **Bead leia-lab-vz3 (norma/artigo vs citacao), handled explicitly** in `seed.normalize_norm`: `{norma, artigo}` →
   `citacao = "<norma>, art. <artigo>"` (just `norma` when `artigo` is empty), extra fields (`status`, `por_que`) are kept, and a
   norm with neither `citacao` nor `norma` **raises** instead of being dropped. A test shows master's `load_risk_matrix` drops those
   norms. I did not touch master's loader (frozen); the fix there is still bead vz3's. `init --matrix <jsonl>` loads the real
   185-risk matrix as an extra type (`locacao_real`; it reuses the locacao classifier text, so keep it out of classifier runs unless you want the ambiguity).
5. **Criticality** is stored as the code uses it (`vermelho/amarelo/verde`).

## Known limits

* `ingest_graph` still keeps `raw_text` in its state (same class of problem; not in scope here, tracked as a follow-up bead).
* The trail keeps a 200-char excerpt of the **masked** clause per `triar` step; masking is best-effort (ADR-0001 Q2).
* No UI, no auth, no per-type matrix version, no snapshot de-duplication (one JSON per analysis).
* Offline Jev/LLM are stubs; nothing here measures real detection quality.

## Notes for the other layers

* **Tracing (B3):** wrap/instrument `build_analyze_minuta_graph(...)` and always feed it through `analyze()`; the state contains
  masked text and the rules snapshot only. The Postgres trail is the audit source; the tracing tool is the debug view.
* **Management (B4):** point the tool at the four domain tables with a `leia_app` member login; `domain_history` is the official
  history (tool-native history is a convenience). `risk_matrix.norms` is jsonb, `kb_chunks` has `vector`/`tsvector` columns.
