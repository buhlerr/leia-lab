"""Harness de verificacao do leia-lab. Rode da raiz do repo com o Python do .venv:

    .venv/Scripts/python.exe .claude/skills/verify-leia-lab/scripts/verify.py <subcomando> --run-id ID ...

Subcomandos:
  launch   cria o banco descartavel leia_lab_verify_<ID> e roda o CLI real ``init`` (``--real`` p/ base+matriz v1)
  doctor   so leitura: servidor, banco, schema, seed, versoes de dado, admin
  cli      roda ``python -m src.cli <args>`` contra o banco descartavel e grava a transcricao
  privacy  sem banco: mascaramento DOCX/TXT, alias do arquivo, grafos recusam texto cru, /ping/ e /
  sql      SELECT em transacao read-only no banco descartavel; grava o resultado
  admin-edit  login + salva um formulario do admin (GET do form, POST com --set CAMPO=VALOR)
  admin-up / admin-down   sobe/derruba o admin Django (runserver) numa porta propria, por PID
  cleanup  derruba o admin desta rodada e apaga o banco; a evidencia fica

Evidencia: .local/verify-proof/<ID>/ (ignorado pelo git; o cleanup nunca apaga).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

REPO = Path(__file__).resolve().parents[4]
PY = Path(sys.executable)
PREFIX = "leia_lab_verify_"
HOMELAB = ("192.168.0.120", 5432, "leia", "LEIA_HOMELAB_PG_PASSWORD")
LOCAL = "postgresql://leia:leia_lab_2026@localhost:5433"
ADMIN_USER, ADMIN_PASS = "verify", "verify-pass-2026"
SECRET = "verify-only-secret-key-not-for-production-0123456789abcdefghij"


def server_dsn() -> str:
    """Servidor sem database: VERIFY_PG_SERVER > homelab (se ha senha) > docker local 5433."""
    if os.environ.get("VERIFY_PG_SERVER"):
        return os.environ["VERIFY_PG_SERVER"].rstrip("/")
    host, port, user, pw_var = HOMELAB
    if os.environ.get(pw_var):
        return f"postgresql://{user}:{quote(os.environ[pw_var], safe='')}@{host}:{port}"
    return LOCAL


def redact(text: str) -> str:
    return re.sub(r"(postgresql://[^:/@]+:)[^@]+@", r"\1***@", text)


def db_name(run_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]{1,40}", run_id):
        raise SystemExit("--run-id: so [a-z0-9_], ate 40 caracteres")
    return PREFIX + run_id


def dsn(run_id: str) -> str:
    return f"{server_dsn()}/{db_name(run_id)}"


def proof_dir(run_id: str) -> Path:
    d = REPO / ".local" / "verify-proof" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_env(run_id: str) -> dict[str, str]:
    """Ambiente do processo filho: banco descartavel, sem chaves pagas, sem tracing implicito."""
    env = dict(os.environ)
    env.update(
        DATABASE_URL=dsn(run_id),
        OPENROUTER_API_KEY="",
        TYPESAFE_API_KEY="",
        LANGSMITH_TRACING="false",
        LEIA_MINUTAS_DIR=str(REPO / "leia-minutas-teste-mascaradas"),
        DJANGO_SECRET_KEY=SECRET,
        DJANGO_DEBUG="true",
        PYTHONIOENCODING="utf-8",
    )
    return env


def next_artifact(run_id: str, slug: str, ext: str) -> Path:
    d = proof_dir(run_id)
    n = len(list(d.glob("[0-9][0-9]-*"))) + 1
    return d / f"{n:02d}-{re.sub(r'[^a-z0-9]+', '-', slug.lower()).strip('-')[:50]}.{ext}"


def run_logged(run_id: str, slug: str, argv: list[str]) -> int:
    started = time.time()
    p = subprocess.run(argv, cwd=REPO, env=run_env(run_id), capture_output=True, text=True, encoding="utf-8")
    out = Path(next_artifact(run_id, slug, "txt"))
    body = (
        f"$ {' '.join(argv[1:]) if argv[0] == str(PY) else ' '.join(argv)}\n"
        f"database={db_name(run_id)} exit={p.returncode} secs={time.time() - started:.1f}\n"
        f"--- stdout\n{p.stdout}--- stderr\n{p.stderr}"
    )
    out.write_text(redact(body), encoding="utf-8")
    sys.stdout.write(redact(p.stdout))
    sys.stderr.write(redact(p.stderr))
    print(f"EVIDENCE {out.relative_to(REPO)} exit={p.returncode}")
    return p.returncode


async def _connect(database: str):
    import asyncpg

    return await asyncpg.connect(f"{server_dsn()}/{database}", timeout=8)


# ---------------------------------------------------------------- subcomandos


async def cmd_launch(a: argparse.Namespace) -> int:
    name = db_name(a.run_id)
    admin = await _connect("postgres")
    try:
        if await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name):
            print(f"banco {name} ja existe; reaproveitando (init e idempotente)")
        else:
            await admin.execute(f'CREATE DATABASE "{name}"')
            print(f"banco {name} criado em {redact(server_dsn())}")
    finally:
        await admin.close()
    args = ["init", "--real"] if a.real else ["init"]
    code = run_logged(a.run_id, "launch-" + "-".join(args), [str(PY), "-m", "src.cli", *args])
    if code == 0:
        print(f"READY database={name}")
    return code


async def cmd_doctor(a: argparse.Namespace) -> int:
    name = db_name(a.run_id)
    report: dict[str, object] = {"server": redact(server_dsn()), "database": name, "python": str(PY)}
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True)
    report["git_head"] = head.stdout.strip()
    ok = True
    try:
        admin = await _connect("postgres")
        report["server_version"] = await admin.fetchval("SHOW server_version")
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name)
        await admin.close()
    except Exception as exc:  # noqa: BLE001 - diagnostico
        report["server_error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    report["database_exists"] = bool(exists)
    if exists:
        c = await _connect(name)
        try:
            await c.execute("SET default_transaction_read_only = on")
            report["tables"] = await c.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            )
            if await c.fetchval("SELECT to_regclass('public.risk_matrix') IS NOT NULL"):
                report["active_risks"] = await c.fetchval("SELECT count(*) FROM risk_matrix WHERE active")
                report["kb_docs"] = await c.fetchval("SELECT count(*) FROM kb_docs")
                report["data_versions"] = [r["name"] for r in await c.fetch("SELECT name FROM data_versions")]
                report["analyses"] = await c.fetchval("SELECT count(*) FROM analyses")
            else:
                ok = False
                report["hint"] = "schema ausente: rode launch"
        finally:
            await c.close()
    else:
        ok = False
        report["hint"] = "banco ausente: rode launch"
    pid_file = proof_dir(a.run_id) / "admin.pid"
    if pid_file.exists():
        port = pid_file.with_name("admin.port").read_text().strip()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping/", timeout=3) as r:
                report["admin"] = f"pid {pid_file.read_text().strip()} porta {port} /ping/ {r.status}"
        except OSError as exc:
            report["admin"] = f"pid {pid_file.read_text().strip()} porta {port} sem resposta: {exc}"
            ok = False
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if ok else 1


def cmd_cli(a: argparse.Namespace) -> int:
    args = [x for x in a.args if x != "--"]
    if not args:
        raise SystemExit("uso: cli --run-id ID -- <args do src.cli>")
    return run_logged(a.run_id, "cli-" + "-".join(args), [str(PY), "-m", "src.cli", *args])


def cmd_privacy(a: argparse.Namespace) -> int:
    out = next_artifact(a.run_id, "privacy", "json")
    probe = Path(__file__).with_name("privacy_probe.py")
    return run_logged(a.run_id, "privacy", [str(PY), str(probe), str(out)])


async def cmd_sql(a: argparse.Namespace) -> int:
    c = await _connect(db_name(a.run_id))
    try:
        async with c.transaction(readonly=True):
            rows = [dict(r) for r in await c.fetch(a.query)]
    finally:
        await c.close()
    text = json.dumps(rows, indent=2, ensure_ascii=False, default=str)
    out = next_artifact(a.run_id, "sql-" + (a.label or "query"), "json")
    out.write_text(json.dumps({"query": a.query, "rows": rows}, indent=2, ensure_ascii=False, default=str), "utf-8")
    print(text)
    print(f"EVIDENCE {out.relative_to(REPO)} rows={len(rows)}")
    return 0


def cmd_admin_up(a: argparse.Namespace) -> int:
    d = proof_dir(a.run_id)
    if (d / "admin.pid").exists():
        raise SystemExit("admin desta rodada ja esta de pe (admin-down antes)")
    manage = [str(PY), "-m", "src.management.manage"]
    if run_logged(a.run_id, "admin-migrate", [*manage, "migrate", "--noinput"]):
        return 1
    env = run_env(a.run_id) | {"DJANGO_SUPERUSER_PASSWORD": ADMIN_PASS}
    subprocess.run(
        [*manage, "createsuperuser", "--noinput", "--username", ADMIN_USER, "--email", "verify@example.invalid"],
        cwd=REPO, env=env, capture_output=True,
    )
    log = open(d / "admin-server.log", "w", encoding="utf-8")  # noqa: SIM115 - fica com o processo filho
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [*manage, "runserver", f"127.0.0.1:{a.port}", "--noreload"],
        cwd=REPO, env=run_env(a.run_id), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
    )
    (d / "admin.pid").write_text(str(proc.pid))
    (d / "admin.port").write_text(str(a.port))
    for _ in range(60):
        if proc.poll() is not None:
            print(f"runserver saiu com {proc.returncode}; veja {d / 'admin-server.log'}")
            (d / "admin.pid").unlink()
            return 1
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{a.port}/ping/", timeout=2) as r:
                if r.status == 200:
                    print(f"ADMIN_READY http://127.0.0.1:{a.port}/admin/ user={ADMIN_USER} pass={ADMIN_PASS} pid={proc.pid}")
                    return 0
        except OSError:
            time.sleep(1)
    print("admin nao respondeu /ping/ em 60s")
    return 1


def cmd_admin_down(a: argparse.Namespace) -> int:
    pid_file = proof_dir(a.run_id) / "admin.pid"
    if not pid_file.exists():
        print("nenhum admin desta rodada")
        return 0
    pid = pid_file.read_text().strip()
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    else:
        subprocess.run(["kill", pid])
    pid_file.unlink()
    pid_file.with_name("admin.port").unlink(missing_ok=True)
    print(f"admin pid {pid} encerrado")
    return 0


class _Form(__import__("html.parser").parser.HTMLParser):
    """Valores atuais do formulario de mudanca do admin (inputs, selects, textareas)."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}
        self._select: str | None = None
        self._textarea: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        at = {k: v or "" for k, v in attrs}
        name = at.get("name")
        if tag == "input" and name and at.get("type") not in ("submit", "button", "file"):
            if at.get("type") == "checkbox":
                if "checked" in at:
                    self.fields[name] = "on"
            else:
                self.fields[name] = at.get("value", "")
        elif tag == "select" and name:
            self._select = name
        elif tag == "option" and self._select and "selected" in at:
            self.fields[self._select] = at.get("value", "")
        elif tag == "textarea" and name:
            self._textarea = name
            self.fields[name] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select = None
        if tag == "textarea":
            self._textarea = None

    def handle_data(self, data: str) -> None:
        if self._textarea:
            self.fields[self._textarea] += data.lstrip("\n") if not self.fields[self._textarea] else data


def cmd_admin_edit(a: argparse.Namespace) -> int:
    """Faz login e salva um formulario do admin como um usuario faria (GET do form, POST com mudancas)."""
    import http.cookiejar
    from urllib.parse import urlencode

    # O Git Bash reescreve "/admin/..." para "C:/Program Files/Git/admin/...": corta ate "admin/".
    a.path = "/" + a.path[a.path.index("admin/"):] if "admin/" in a.path else a.path
    d = proof_dir(a.run_id)
    port_file = d / "admin.port"
    if not port_file.exists():
        raise SystemExit("admin desta rodada nao esta de pe: admin-up antes")
    base = f"http://127.0.0.1:{port_file.read_text().strip()}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def csrf() -> str:
        return next(c.value for c in jar if c.name == "csrftoken")

    def post(path: str, data: dict[str, str]):
        req = urllib.request.Request(base + path, urlencode(data).encode(), headers={"Referer": base + path})
        return opener.open(req)

    opener.open(base + "/admin/login/?next=/admin/")
    r = post("/admin/login/?next=/admin/", {"csrfmiddlewaretoken": csrf(), "username": ADMIN_USER, "password": ADMIN_PASS})
    if r.url.rstrip("/").endswith("/admin/login"):
        raise SystemExit("login falhou")
    form = _Form()
    form.feed(opener.open(base + a.path).read().decode("utf-8"))
    before = dict(form.fields)
    changes = dict(kv.split("=", 1) for kv in a.set)
    for k in changes:
        if k not in before:
            raise SystemExit(f"campo {k!r} nao existe no formulario; campos: {sorted(before)}")
    data = {k: v for k, v in (before | changes).items() if not k.startswith("_")}
    data["csrfmiddlewaretoken"] = csrf()
    data["_save"] = "Salvar"
    r = post(a.path, data)
    body = r.read().decode("utf-8")
    errors = re.findall(r'<ul class="errorlist[^"]*"[^>]*>(.*?)</ul>', body, re.S)
    saved = not errors and not r.url.endswith(a.path)
    out = next_artifact(a.run_id, "admin-edit-" + a.path, "json")
    proof = {
        "path": a.path,
        "changes": changes,
        "before": {k: before[k] for k in changes},
        "status": r.status,
        "final_url": r.url.replace(base, ""),
        "saved": saved,
        "errors": [re.sub(r"<[^>]+>", " ", e).strip() for e in errors],
    }
    out.write_text(json.dumps(proof, indent=2, ensure_ascii=False), "utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=False))
    print(f"EVIDENCE {out.relative_to(REPO)} saved={saved}")
    return 0 if saved else 1


async def cmd_cleanup(a: argparse.Namespace) -> int:
    cmd_admin_down(a)
    # gold-run grava .local/gold-runs/<label>.json, pasta das rodadas reais: as da verificacao
    # (label "<run_id>-...") vao para a evidencia em vez de ficar misturadas la.
    moved = proof_dir(a.run_id) / "gold-runs"
    for f in (REPO / ".local" / "gold-runs").glob(f"{a.run_id}-*.json"):
        moved.mkdir(exist_ok=True)
        f.replace(moved / f.name)
        print(f"rodada {f.name} movida para {moved.relative_to(REPO)}")
    name = db_name(a.run_id)
    assert name.startswith(PREFIX)
    admin = await _connect("postgres")
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1 AND pid<>pg_backend_pid()", name
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await admin.close()
    print(f"CLEANED database={name}; evidencia preservada em {proof_dir(a.run_id).relative_to(REPO)}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="verify.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("launch", "doctor", "cli", "privacy", "sql", "admin-up", "admin-edit", "admin-down", "cleanup"):
        s = sub.add_parser(name)
        s.add_argument("--run-id", required=True)
        if name == "launch":
            s.add_argument("--real", action="store_true", help="init --real: base normativa + matriz v1")
        if name == "cli":
            s.add_argument("args", nargs=argparse.REMAINDER)
        if name == "sql":
            s.add_argument("query")
            s.add_argument("--label", default="")
        if name == "admin-up":
            s.add_argument("--port", type=int, default=8011)
        if name == "admin-edit":
            s.add_argument("--path", required=True, help="ex.: /admin/domain/riskmatrix/1/change/")
            s.add_argument("--set", action="append", default=[], metavar="CAMPO=VALOR")
    a = p.parse_args()
    fn = {
        "launch": cmd_launch, "doctor": cmd_doctor, "cli": cmd_cli, "privacy": cmd_privacy, "sql": cmd_sql,
        "admin-up": cmd_admin_up, "admin-edit": cmd_admin_edit, "admin-down": cmd_admin_down, "cleanup": cmd_cleanup,
    }[a.cmd]
    res = fn(a)
    raise SystemExit(asyncio.run(res) if asyncio.iscoroutine(res) else res)


if __name__ == "__main__":
    main()
