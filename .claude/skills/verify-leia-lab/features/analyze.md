# Analyze a minuta

A user runs one analysis on a contract file. The file is read and masked locally, the pipeline classifies it, splits it into clauses, checks each clause against the active risk matrix, and prints the analysis id, status, matrix and prompt versions and the alerts. The run leaves an immutable `analyses` row and an append-only `analysis_trail`.

## Sub-features

- `analyze-run` prints `analysis_id=... status=done ... alertas=[...]` and exits 0.
- `analyze-persist` writes one `analyses` row with `status=done`, `finished_at` set and the same `matrix_version`.
- `analyze-trail` writes trail rows for the steps `iniciar`, `classificar`, `ficha`, `triar`, `buscar`, `analisar`, `validar`.
- `analyze-privacy` stores only the alias `documento-<sha8>.<ext>`, never the real filename.
- `analyze-formats` accepts `.txt`, `.docx` and `.pdf`.

## How to get to it (user POV)

- `python -m src.cli analyze <file>` (optionally `--trace`, out of scope here).

## Driving it with verify.py

Preconditions:

- `$V launch --run-id r1` done (default seed is enough; `--real` also works).
- `$V doctor --run-id r1` shows `"analyses": 0` if you want the counts below to be exact.

- **Run an analysis.** `$V cli --run-id r1 -- analyze leia-minutas-teste-mascaradas/locacao-01.txt`. Exit 0 and stdout `analysis_id=<uuid> status=done matrix_version=<12 hex> prompt_version=<12 hex> alertas=[('R-04', 'yellow')]` with the default seed. stderr carries one warning about offline hash embeddings; that is expected.
- **Confirm the row and trail.** `$V sql --run-id r1 --label analyze-row "SELECT a.id, a.status, a.filename_alias, a.matrix_version, a.finished_at IS NOT NULL AS finished, (SELECT count(*) FROM analysis_trail t WHERE t.analysis_id=a.id) AS trail_rows, (SELECT array_agg(DISTINCT step) FROM analysis_trail t WHERE t.analysis_id=a.id) AS steps, a.report::text ILIKE '%locacao-01%' AS raw_name_leaked FROM analyses a"`. One row: same id as stdout, `status` `done`, `filename_alias` like `documento-40e582b0.txt`, `finished` true, `trail_rows` > 0 (69 for locacao-01 on the default seed), the seven steps above, `raw_name_leaked` false.
- **Other formats.** Make a `.docx` copy with python-docx in the scratchpad (not in the repo) and run `analyze` on it; the alias ends in `.docx`.
- **Proof.** The `NN-cli-analyze-...txt` transcript and the `NN-sql-analyze-row.json` in `.local/verify-proof/r1/`.

## Gotchas

- Offline the Jev stub always picks the first theme, so every minuta gets the same `R-04` alert on the default seed. Different alerts across minutas need real keys; do not treat identical alerts as a bug of your change.
- `analyses` and `analysis_trail` reject UPDATE/DELETE/TRUNCATE by trigger. You cannot reset them; use a new run id for a clean count.
- The test minutas are already masked (`[CNPJ]` marks). To check masking itself, use a scratch file with a fake CPF/e-mail and confirm the `analysis_trail.input_summary` contains `[CPF]`/`[EMAIL]` and not the raw value.
- A path outside the repo works, but the filename never reaches the database; only the alias does.
