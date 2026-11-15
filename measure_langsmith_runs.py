"""Mede quantos RUNS a LangSmith recebe por análise e quantos são RAÍZES (trace).

O SDK manda um POST /runs por run (create) e um PATCH /runs/{id} no fim, então
contamos os POSTs e a hierarquia por parent_run_id. Nada sai para a nuvem:
o client aponta para um capturador local.
"""

import asyncio
import json
import os
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CAPTURED: list[tuple[str, str, bytes]] = []


class Handler(BaseHTTPRequestHandler):
    def _read(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_POST(self) -> None:  # noqa: N802
        body = self._read()
        CAPTURED.append(("POST", self.path, body))
        payload = b'{"id": "00000000-0000-0000-0000-000000000000"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_PATCH(self) -> None:  # noqa: N802
        body = self._read()
        CAPTURED.append(("PATCH", self.path, body))
        payload = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


async def main() -> None:
    import asyncpg
    import langsmith
    from langsmith import Client

    from src.config import Settings
    from src.foundation.seed import seed_defaults
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    client = Client(
        api_url=f"http://127.0.0.1:{port}",
        api_key="lsv2_pt_local_only",
        auto_batch_tracing=False,
    )
    langsmith.configure(client=client, enabled=True, project_name="leia-measure")

    settings = Settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=4)
    try:
        await seed_defaults(pool)
        graph = build_analyze_minuta_graph(pool, settings)
        minuta = os.path.join(os.environ["LEIA_MINUTAS_DIR"], "locacao-01.txt")
        await analyze(graph, file_path=minuta)
    finally:
        await pool.close()
        client.flush()
        server.shutdown()

    runs: dict[str, dict] = {}
    for method, path, body in CAPTURED:
        if method != "POST" or not path.rstrip("/").endswith("/runs"):
            continue
        try:
            data = json.loads(body)
        except Exception:  # noqa: BLE001
            continue
        rid = data.get("id")
        if rid:
            runs[rid] = data

    roots = [r for r in runs.values() if not r.get("parent_run_id")]
    kinds = Counter(r.get("run_type", "?") for r in runs.values())

    print("ANALISE: locacao-01.txt (mesma do Phoenix)")
    print(f"RUNS TOTAIS enviados: {len(runs)}")
    print(f"RUNS-RAIZ (o que a LangSmith chama de 'trace'): {len(roots)}")
    for r in roots:
        print(f"   raiz: {r.get('name')} [{r.get('run_type')}]")
    print("por run_type:", dict(kinds))
    print(
        f"ORCAMENTO 5.000 tracos/mes => ~{int(5000 / max(len(roots), 1))} analises/mes (contando raizes)"
    )
    print(
        f"ORCAMENTO 5.000 tracos/mes => ~{int(5000 / max(len(runs), 1))} analises/mes (contando todo run)"
    )


if __name__ == "__main__":
    asyncio.run(main())
