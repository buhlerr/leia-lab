"""CLI: ``python -m src.cli <comando>``. Usa DATABASE_URL (ambiente ou .env).

Comandos:
* ``init``: aplica o schema e o seed padrao (idempotente).
* ``init --real``: idem + base normativa e matriz real versionadas em ``data/`` (Q5; idempotente,
  retomavel). Indexar a base gera embeddings (pago com OPENROUTER_API_KEY).
* ``data-versions``: versoes de dados ja aplicadas no banco.
* ``apply-matrix --versao X``: troca so a matriz ativa (ex.: ``v2`` sem reindexar a base).
* ``analyze <arquivo>``: uma analise; o arquivo e lido e mascarado localmente.
* ``gold-run --label X``: analisa as minutas do gabarito (LEIA_MINUTAS_DIR) e mede P/R/F1.
* ``gold-compare A B``: compara duas rodadas rotuladas (ex.: antes e depois de editar a matriz).
* ``trace-usage``: tracos do mes na LangSmith contra o limite do plano (sai com 2 em alerta).

``--trace`` em ``analyze``/``gold-run`` envia o traco aos backends configurados (LangSmith/MLflow, so conteudo mascarado).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import asyncpg

from src.config import Settings
from src.db.connection import init_db
from src.db.seed import seed_defaults
from src.db.versions import applied_versions, apply_base, apply_matrix
from src.eval import gold as G
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph
from src.graphs.ingest_graph import build_ingest_graph, ingest

RUNS_DIR = Path(".local") / "gold-runs"  # ignorado pelo git; so ids de analise


async def gold_run(pool: asyncpg.Pool, settings: Settings, minutas_dir: Path) -> dict[str, Any]:
    """Analisa as minutas do gabarito e pontua; ``analyses`` guarda o que foi detectado."""
    gold = G.load_gold()
    problems = G.verify_gold(gold, minutas_dir)
    if problems:
        raise SystemExit("o gabarito nao confere com as minutas locais:\n" + "\n".join(problems))
    graph = build_analyze_minuta_graph(pool, settings)
    ids = {name: (await analyze(graph, file_path=minutas_dir / name))["analysis_id"] for name in gold["minutas"]}
    versions = await pool.fetchrow(
        "SELECT matrix_version, prompt_version FROM analyses WHERE id = $1::uuid", next(iter(ids.values()))
    )
    return {"analyses": ids, **dict(versions), "score": G.score(gold, await G.detected_from_analyses(pool, ids))}


async def gold_compare(pool: asyncpg.Pool, a: dict[str, str], b: dict[str, str]) -> dict[str, Any]:
    """Re-pontua duas rodadas a partir de ``analyses`` (comparavel mesmo depois de a matriz mudar)."""
    gold = G.load_gold()
    sa = G.score(gold, await G.detected_from_analyses(pool, a))
    sb = G.score(gold, await G.detected_from_analyses(pool, b))
    return {"a": sa, "b": sb, **G.compare(sa, sb)}


def _line(label: str, s: dict[str, Any]) -> str:
    line = f"[{label}] P={s['precision']} R={s['recall']} F1={s['f1']} exact={s['exact_match']}"
    severity = s.get("severity") or {}
    if severity.get("accuracy") is not None:
        line += f" sev={severity['correct']}/{severity['compared']} ({severity['accuracy']})"
    return line


def _trace_usage(args: argparse.Namespace) -> int:
    import os

    from langsmith import Client

    from src.tracing import trace_usage

    project = args.project or os.environ.get("LANGSMITH_PROJECT") or "leia-lab"
    res = trace_usage(Client(), project, limit=args.limit, warn_at=args.warn)
    print(f"[{res['status']}] {res['traces']}/{res['limit']} tracos em {res['project']} desde {res['since']}")
    return 0 if res["status"] == "ok" else 2


async def _main(args: argparse.Namespace) -> None:
    settings = Settings()
    tracing: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()
    if getattr(args, "trace", False):
        from src.tracing import tracing_session

        tracing = tracing_session()
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=4)
    try:
        with tracing:
            if args.cmd == "init":
                await init_db(pool)
                print("seed aplicado:", await seed_defaults(pool))
                if args.real:
                    graph = build_ingest_graph(pool, settings)

                    async def ingest_fn(texto: str, citacao: str, source: str) -> None:
                        await ingest(graph, raw_text=texto, doc_name=citacao, source=source)

                    print("base normativa: artigos indexados agora =", await apply_base(pool, ingest_fn, args.versao))
                    print("matriz aplicada:", await apply_matrix(pool, args.versao, base_version=args.versao))
            elif args.cmd == "data-versions":
                for name, sha in (await applied_versions(pool)).items():
                    print(f"{name} {sha[:12]}")
            elif args.cmd == "apply-matrix":
                print("matriz aplicada:", await apply_matrix(pool, args.versao, base_version=args.base_versao))
            elif args.cmd == "analyze":
                out = await analyze(build_analyze_minuta_graph(pool, settings), file_path=args.file)
                alerts = sorted({(x["risk_id"], x["severity"]) for x in out["report_envelope"]["content"]["alerts"]})
                print(
                    f"analysis_id={out['analysis_id']} status={out['report_envelope']['status']} "
                    f"matrix_version={out['rules_meta']['matrix_version']} "
                    f"prompt_version={out['rules_meta']['prompt_version']} alertas={alerts}"
                )
            elif args.cmd == "gold-run":
                res = await gold_run(pool, settings, G.minutas_dir())
                RUNS_DIR.mkdir(parents=True, exist_ok=True)
                (RUNS_DIR / f"{args.label}.json").write_text(json.dumps({"analyses": res["analyses"]}), encoding="utf-8")
                print(f"matrix={res['matrix_version']} prompt={res['prompt_version']} " + _line(args.label, res["score"]))
            elif args.cmd == "gold-compare":
                runs = [json.loads((RUNS_DIR / f"{x}.json").read_text(encoding="utf-8"))["analyses"] for x in (args.a, args.b)]
                res = await gold_compare(pool, *runs)
                print(_line(args.a, res["a"]))
                print(_line(args.b, res["b"]))
                print("delta (b-a):", res["delta"])
                for cid, ch in res["changed_clauses"].items():
                    print(f"  {cid}: esperado={ch['expected']} {ch['from']} -> {ch['to']}")
    finally:
        await pool.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m src.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="aplica o schema e o seed padrao (idempotente)")
    i.add_argument("--real", action="store_true", help="aplica tambem a base normativa e a matriz real de data/")
    i.add_argument("--versao", default="v1", help="versao de data/ para base e matriz (padrao v1)")
    sub.add_parser("data-versions", help="versoes de dados ja aplicadas no banco")
    m = sub.add_parser("apply-matrix", help="aplica/troca a matriz ativa sem reindexar a base")
    m.add_argument("--versao", default="v1", help="versao da matriz (padrao v1)")
    m.add_argument("--base-versao", default="v1", help="versao da base normativa para mapear normas (padrao v1)")
    a = sub.add_parser("analyze", help="uma analise (arquivo lido e mascarado localmente)")
    a.add_argument("file")
    g = sub.add_parser("gold-run", help="analisa as minutas do gabarito (LEIA_MINUTAS_DIR) e pontua")
    g.add_argument("--label", required=True)
    for cmd in (a, g):
        cmd.add_argument(
            "--trace", action="store_true", help="envia o traco a LangSmith e/ou MLflow (so conteudo mascarado)"
        )
    c = sub.add_parser("gold-compare", help="compara duas rodadas rotuladas")
    c.add_argument("a")
    c.add_argument("b")
    u = sub.add_parser("trace-usage", help="tracos do mes na LangSmith contra o limite do plano")
    u.add_argument("--limit", type=int, default=5000, help="limite do plano (Developer: 5.000/mes)")
    u.add_argument("--warn", type=float, default=0.8, help="fracao do limite que dispara o alerta")
    u.add_argument("--project", default=None)
    args = p.parse_args()
    if args.cmd == "trace-usage":
        raise SystemExit(_trace_usage(args))
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
