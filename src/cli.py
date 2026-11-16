"""CLI: ``python -m src.cli <comando>``. Usa DATABASE_URL (ambiente ou .env).

Comandos:
* ``init``: aplica o schema e o seed padrao (idempotente).
* ``analyze <arquivo>``: uma analise; o arquivo e lido e mascarado localmente.
* ``gold-run --label X``: analisa as minutas do gabarito (LEIA_MINUTAS_DIR) e mede P/R/F1.
* ``gold-compare A B``: compara duas rodadas rotuladas (ex.: antes e depois de editar a matriz).

``--trace`` em ``analyze``/``gold-run`` envia o traco a LangSmith (so conteudo mascarado).
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
from src.eval import gold as G
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

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
    return f"[{label}] P={s['precision']} R={s['recall']} F1={s['f1']} exact={s['exact_match']}"


async def _main(args: argparse.Namespace) -> None:
    settings = Settings()
    tracing: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()
    if getattr(args, "trace", False):
        from src.tracing import langsmith_tracing

        tracing = langsmith_tracing()
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=4)
    try:
        with tracing:
            if args.cmd == "init":
                await init_db(pool)
                print("seed aplicado:", await seed_defaults(pool))
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
    sub.add_parser("init", help="aplica o schema e o seed padrao (idempotente)")
    a = sub.add_parser("analyze", help="uma analise (arquivo lido e mascarado localmente)")
    a.add_argument("file")
    g = sub.add_parser("gold-run", help="analisa as minutas do gabarito (LEIA_MINUTAS_DIR) e pontua")
    g.add_argument("--label", required=True)
    for cmd in (a, g):
        cmd.add_argument("--trace", action="store_true", help="envia o traco a LangSmith (so conteudo mascarado)")
    c = sub.add_parser("gold-compare", help="compara duas rodadas rotuladas")
    c.add_argument("a")
    c.add_argument("b")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
