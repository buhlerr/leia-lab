# Privacy boundary

Every file a user hands to leia-lab is read and masked locally before anything enters a LangGraph state, a database row or a trace. CPF, e-mail and party names become tokens (`[CPF]`, `[EMAIL]`), the filename becomes `documento-<sha8>.<ext>`, and both graphs refuse unmasked input when invoked directly. This recipe proves the boundary offline, without any database, so it still works when Postgres is unreachable.

## Sub-features

- `mask-pii` replaces CPF and e-mail in `.docx` and `.txt` input with `[CPF]` and `[EMAIL]`.
- `alias-filename` turns `Minuta_Particular_Maria_<cpf>.docx` into `documento-<sha8>.docx`.
- `ingest-doc-name` keeps a normativa citation passed as `doc_name` verbatim (`Lei 8.245/1991, art. 35`).
- `reject-unmasked` makes `analyze_minuta_graph` and `ingest_graph` raise `ValueError` on raw text passed to `.ainvoke()`.
- `ficha-candidates` extracts dates, deadlines and amounts from the masked text.
- `admin-entrypoints` answers `GET /ping/` with `200 {"ok": true}` and redirects `GET /` to `/admin/`.

## How to get to it (user POV)

- `python -m src.cli analyze <file>` and `ingest`, which call `prepare_input` / `prepare_ingest_input` before the graph.
- Uploading a document in the admin, which goes through the same functions.

## Driving it with verify.py

Preconditions:

- `.venv` installed (`python-docx` and Django import). No `launch` needed: this command never opens a database connection.

- **Run the probe.** `$V privacy --run-id p1`. It builds a fake DOCX and TXT with a CPF, e-mail and name in a temp folder, runs them through the real entry functions, invokes both graphs with raw text, and hits the admin with the Django test client. Exit 0 and the last lines are `PRIVACY_OK` and `EVIDENCE .local/verify-proof/p1/NN-privacy.txt exit=0`.
- **Read the proof.** `.local/verify-proof/p1/NN-privacy.json` has `"failed_checks": []`, every `raw_*_leaked` false, `cpf_token_present`/`email_token_present`/`alias_ok` true, `analyze_rejects_unmasked` and `ingest_rejects_unmasked` true, `"ping": [200, {"ok": true}]` and `"root": [302, "/admin/"]`.
- **Failure.** Exit 1 and `PRIVACY_FAIL [<check names>]`; the JSON lists the same names in `failed_checks`.

## Gotchas

- This probe calls `prepare_input`/`prepare_ingest_input` and `.ainvoke()` from Python on purpose: they are the boundary under test. For the end-to-end claim that no raw data reaches the database, also run the masking check in [analyze.md](./analyze.md) against a launched run.
- `doc_name` is stored verbatim by design. Never pass a client's personal filename there.
- PDF extraction is not covered here; use `analyze` on a scratch PDF if your change touches it.
