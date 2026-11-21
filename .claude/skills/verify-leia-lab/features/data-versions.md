# Data versions

An operator loads the versioned real data from `data/` into the database: the base normativa (legal articles, indexed with embeddings) and a risk matrix version. Each version enters once, is checked by sha256 against its manifest, and is recorded in the append-only `data_versions`. Switching matrix version deactivates risks that left and updates changed ones, logging each change in `domain_history`.

## Sub-features

- `init-real` applies schema, seed, base normativa v1 and matriz v1.
- `apply-matrix` switches the active matrix (`v2`, `v3`) without reindexing the base.
- `data-versions` lists applied versions with their sha256 prefix.
- `matrix-diff` deactivates removed risks (`R176` in v2) and updates changed criticality (`R054` in v2, `R007` in v3).

## How to get to it (user POV)

- `python -m src.cli init --real [--versao v1]`
- `python -m src.cli apply-matrix --versao v3 --base-versao v1`
- `python -m src.cli data-versions`

## Driving it with verify.py

Preconditions:

- A fresh run id, no `launch` yet.

- **Load real data.** `$V launch --run-id r1 --real`. Exit 0 in about 10 s, stdout `base normativa: artigos indexados agora = 330`, `matriz aplicada: True`, `READY database=leia_lab_verify_r1`. `doctor` then shows `kb_docs` 330, `active_risks` 185, `data_versions` `["base-normativa/v1", "matriz/v1"]`.
- **Re-run is idempotent.** `$V launch --run-id r1 --real` again. `artigos indexados agora = 0`.
- **Switch matrix.** `$V cli --run-id r1 -- apply-matrix --versao v3 --base-versao v1`. stdout `matriz aplicada: True`.
- **List versions.** `$V cli --run-id r1 -- data-versions`. Lines `base-normativa/v1 77938bfab46f`, `matriz/v1 a982811c2647`, `matriz/v3 ef3247462476`.
- **Confirm the matrix diff.** `$V sql --run-id r1 --label matrix-v3 "SELECT risk_id, criticality, active FROM risk_matrix WHERE risk_id IN ('R007','R054','R176') ORDER BY risk_id"`. `R007` vermelho active, `R054` vermelho active, `R176` active false.
- **Proof.** The transcripts plus `NN-sql-matrix-v3.json`.

## Gotchas

- Without `OPENROUTER_API_KEY` the base is indexed with `offline-hash-v1` embeddings: fast and free, but search over them is not semantic.
- The sha prefixes above are for the files committed today; a new `data/` version changes them. Editing a published version file must make `init --real`/`apply-matrix` refuse (sha mismatch); that refusal is the expected behavior, not a failure of the harness.
- `data_versions` is append-only: applying `v3` then `v1` again does not remove the `v3` line.
