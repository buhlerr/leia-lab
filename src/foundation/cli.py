"""Prototype CLI: ``python -m src.foundation.cli <command>``. Uses DATABASE_URL (env or .env)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import asyncpg

from src.config import Settings
from src.foundation import gold as G
from src.foundation.db import init_foundation
from src.foundation.seed import load_matrix_jsonl, seed_defaults
from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph
from src.tracing import TOOLS

RUNS_DIR = Path(".local") / "gold-runs"  # git-ignored; holds analysis ids + risk ids only


async def _main(args: argparse.Namespace) -> None:
    if getattr(args, "trace", "off") != "off":
        from src.tracing import setup_tracing

        print("tracing:", setup_tracing(args.trace))
    settings = Settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=4)
    try:
        if args.cmd == "init":
            await init_foundation(pool)
            print("seeded defaults:", await seed_defaults(pool))
            if args.matrix:
                print("loaded real matrix risks:", await load_matrix_jsonl(pool, args.slug, Path(args.matrix)))
        elif args.cmd == "analyze":
            graph = build_analyze_minuta_graph(pool, settings)
            out = await analyze(graph, file_path=args.file)
            a = await pool.fetchrow("SELECT id, status, matrix_version, prompt_version FROM analyses WHERE id=$1::uuid", out["analysis_id"])
            alerts = [(x["risk_id"], x["severity"]) for x in out["report_envelope"]["content"]["alerts"]]
            print(f"analysis_id={a['id']} status={a['status']} matrix_version={a['matrix_version']} "
                  f"prompt_version={a['prompt_version']} alerts={len(alerts)} {sorted(set(alerts))[:6]}")
        elif args.cmd == "gold-run":
            gold = G.load_gold()
            d = G.minutas_dir()
            problems = G.verify_gold(gold, d)
            if problems:
                raise SystemExit("gold set does not match local minutas:\n" + "\n".join(problems))
            graph = build_analyze_minuta_graph(pool, settings)
            ids = {}
            for name in gold["minutas"]:
                out = await analyze(graph, file_path=d / name)
                ids[name] = out["analysis_id"]
            res = G.score(gold, await G.detected_from_analyses(pool, ids))
            row = await pool.fetchrow("SELECT matrix_version, prompt_version FROM analyses WHERE id=$1::uuid", next(iter(ids.values())))
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / f"{args.label}.json").write_text(json.dumps({"analyses": ids}), encoding="utf-8")
            print(f"[{args.label}] matrix={row['matrix_version']} prompt={row['prompt_version']} "
                  f"P={res['precision']} R={res['recall']} F1={res['f1']} exact={res['exact_match']}")
        elif args.cmd == "gold-compare":
            gold = G.load_gold()
            res = {}
            for label in (args.a, args.b):
                ids = json.loads((RUNS_DIR / f"{label}.json").read_text(encoding="utf-8"))["analyses"]
                res[label] = G.score(gold, await G.detected_from_analyses(pool, ids))
                print(f"[{label}] P={res[label]['precision']} R={res[label]['recall']} F1={res[label]['f1']} exact={res[label]['exact_match']}")
            cmp = G.compare(res[args.a], res[args.b])
            print("delta (b-a):", cmp["delta"])
            for cid, ch in cmp["changed_clauses"].items():
                print(f"  {cid}: expected={ch['expected']} {ch['from']} -> {ch['to']}")
    finally:
        await pool.close()
        if getattr(args, "trace", "off") != "off":
            from src.tracing import force_flush

            force_flush()


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m src.foundation.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="apply schemas and seed locacao_residencial from master's defaults")
    i.add_argument("--matrix", help="also load the real matrix JSONL as an extra minuta type")
    i.add_argument("--slug", default="locacao_real")
    a = sub.add_parser("analyze", help="run one analysis (raw file is read + masked locally)")
    a.add_argument("file")
    g = sub.add_parser("gold-run", help="analyse the gold minutas (LEIA_MINUTAS_DIR) and score them")
    g.add_argument("--label", required=True)
    for cmd in (a, g):
        cmd.add_argument("--trace", choices=list(TOOLS), default="off",
                         help="registration tool: langsmith|langfuse|phoenix (env keys, never files)")
    c = sub.add_parser("gold-compare", help="compare two labelled gold runs")
    c.add_argument("a")
    c.add_argument("b")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
