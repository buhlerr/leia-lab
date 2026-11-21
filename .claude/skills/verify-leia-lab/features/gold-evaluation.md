# Gold evaluation

A user scores the pipeline against the gold set (`gold/gold_set.json`): `gold-run` analyses every gold minuta, compares detected risk ids per clause with the expected ones, prints precision, recall, F1, exact clause matches and severity accuracy, and saves the run's analysis ids under a label. `gold-compare` re-scores two labelled runs from the stored analyses and prints the delta and the clauses that changed.

## Sub-features

- `gold-run` prints `matrix=... prompt=... [label] P=... R=... F1=... exact=n/17 sev=c/k (acc)`.
- `gold-label` writes `.local/gold-runs/<label>.json` with the analysis ids.
- `gold-compare` prints both lines, `delta (b-a): {...}` and changed clauses.
- `gold-severity` counts expected severities (`R054` red, `R007` red, ...) and moves when the matrix changes criticality.
- `gold-guard` refuses to run when the gold set does not match the local minutas.

## How to get to it (user POV)

- `python -m src.cli gold-run --label <label>` (needs `LEIA_MINUTAS_DIR`; the helper sets it)
- `python -m src.cli gold-compare <label-a> <label-b>`

## Driving it with verify.py

Preconditions:

- `$V launch --run-id r1 --real` done (gold risk ids are real matrix ids like `R007`; the default seed has none of them).
- `leia-minutas-teste-mascaradas/` holds the masked minutas listed in the gold set.

- **Baseline run on matrix v1.** `$V cli --run-id r1 -- gold-run --label r1-a`. Exit 0 in about 5 s; offline today: `[r1-a] P=0.025 R=0.1 F1=0.04 exact=0/17 sev=2/3 (0.667)`.
- **Change the matrix.** `$V cli --run-id r1 -- apply-matrix --versao v3 --base-versao v1`.
- **Second run.** `$V cli --run-id r1 -- gold-run --label r1-b`. Offline today: `sev=3/3 (1.0)`, ids unchanged.
- **Compare.** `$V cli --run-id r1 -- gold-compare r1-a r1-b`. Both lines and `delta (b-a): {'precision': 0.0, 'recall': 0.0, 'f1': 0.0}`.
- **Confirm stored runs.** `$V sql --run-id r1 --label gold-analyses "SELECT matrix_version, count(*) FROM analyses GROUP BY 1"`. Two matrix versions, one row per gold minuta each.
- **Proof.** Transcripts, the SQL JSON, and after cleanup `.local/verify-proof/r1/gold-runs/r1-a.json` and `r1-b.json`.

## Gotchas

- Offline numbers prove the scoring mechanism only (Jev stub picks the first theme). The real baseline (F1 0.717 on matrix v3) needs paid keys via Shelve; do not compare offline F1 with it.
- `.local/gold-runs/` also holds the user's real runs (`real-v1`, `gold-goldv3-matrizv3`, ...). Never reuse those labels; prefix with the run id so cleanup moves yours out.
- `gold-compare` reads analyses from the current run's database. Labels from another database (or from the user's real runs) point to ids that do not exist here.
