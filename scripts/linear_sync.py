"""Sincroniza o Beads com o Linear (time VIT) so quando algo mudou.

Uso, da raiz do repo:  op run --env-file=.env.op -- scripts/linear-sync.sh [--dry-run]

1. Puxa do Linear so se alguma issue do time mudou desde a ultima rodada.
2. Envia so os beads novos ou que mudaram (hash de titulo, descricao, status, prioridade,
   rotulos e pai): os abertos, e os fechados que ja estao no Linear (para irem a Done la).
   As 62 tarefas fechadas antes do espelho nunca vao.
3. Poe no projeto leia-lab toda issue deste repo que esteja sem projeto (o bd nao sabe de projetos).

O estado (hashes e horario da ultima rodada) fica em .local/linear-sync-state.json, fora do git e por
maquina: uma maquina sem estado faz uma rodada completa.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT = "leia-lab"
TEAM_ID = "c68fd49b-1dc2-4053-9470-e0674aa881a1"
STATE = Path(".local/linear-sync-state.json")
API = "https://api.linear.app/graphql"
USER_AGENT = "leia-lab-linear-sync (+https://github.com/buhlerr/leia-lab)"
_IDENT = re.compile(r"linear\.app/[^/]+/issue/([A-Z]+-\d+)")
_PUSHED_FIELDS = ("title", "description", "acceptance_criteria", "status", "priority", "issue_type", "labels", "parent")
BD = shutil.which("bd-go") or shutil.which("bd") or "bd"


def gql(query: str, variables: dict | None = None) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": os.environ["LINEAR_API_KEY"], "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise SystemExit(f"Linear: {body['errors']}")
    return body["data"]


def bd(*args: str) -> None:
    subprocess.run([BD, *args], check=True)


def beads() -> list[dict]:
    out = subprocess.run([BD, "list", "--all", "--json"], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def fingerprint(b: dict) -> str:
    data = {k: b.get(k) for k in _PUSHED_FIELDS}
    data["labels"] = sorted(data["labels"] or [])
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def linear_changed_since(since: str | None) -> bool:
    if since is None:
        return True
    found = gql(
        "query($t: ID!, $s: DateTimeOrDuration!) { issues(first: 1, filter: {team: {id: {eq: $t}}, updatedAt: {gt: $s}}) { nodes { id } } }",
        {"t": TEAM_ID, "s": since},
    )
    return bool(found["issues"]["nodes"])


def to_push(all_beads: list[dict], hashes: dict[str, str]) -> list[str]:
    ids = []
    for b in all_beads:
        linked = "linear.app" in (b.get("external_ref") or "")
        if b["status"] == "closed" and not linked:
            continue
        if hashes.get(b["id"]) != fingerprint(b):
            ids.append(b["id"])
    return ids


def assign_project(all_beads: list[dict], dry_run: bool) -> list[str]:
    linked = {m.group(1) for b in all_beads if (m := _IDENT.search(b.get("external_ref") or ""))}
    projects = gql("query($n: String!) { projects(filter: {name: {eq: $n}}) { nodes { id } } }", {"n": PROJECT})
    if not projects["projects"]["nodes"]:
        raise SystemExit(f"Linear: projeto {PROJECT!r} nao existe; crie-o no time antes de sincronizar")
    project_id = projects["projects"]["nodes"][0]["id"]
    loose, after = [], None
    while True:
        page = gql(
            "query($a: String) { issues(first: 100, after: $a, filter: {project: {null: true}}) "
            "{ nodes { id identifier } pageInfo { hasNextPage endCursor } } }",
            {"a": after},
        )["issues"]
        loose += [n for n in page["nodes"] if n["identifier"] in linked]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    if not dry_run:
        for issue in loose:
            gql(
                "mutation($id: String!, $p: String!) { issueUpdate(id: $id, input: {projectId: $p}) { success } }",
                {"id": issue["id"], "p": project_id},
            )
    return sorted(i["identifier"] for i in loose)


def main() -> None:
    dry_run = "--dry-run" in sys.argv[1:]
    extra = ["--dry-run"] if dry_run else []
    state = json.loads(STATE.read_text()) if STATE.is_file() else {"last_sync": None, "hashes": {}}
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    if linear_changed_since(state["last_sync"]):
        print("Linear mudou desde a ultima rodada: puxando")
        bd("linear", "sync", "--pull", *extra)
    else:
        print("Linear sem mudancas desde a ultima rodada")

    current = beads()
    pending = to_push(current, state["hashes"])
    if pending:
        print(f"Enviando {len(pending)} bead(s): {', '.join(pending)}")
        bd("linear", "sync", "--push", "--issues", ",".join(pending), *extra)
        current = beads()
    else:
        print("Beads sem mudancas desde a ultima rodada")

    moved = assign_project(current, dry_run) if pending else []
    if moved:
        print(f"{len(moved)} issue(s) {'iria(m)' if dry_run else 'foi(foram)'} para o projeto {PROJECT}: {', '.join(moved)}")

    if not dry_run:
        # Depois do envio: as issues que este envio tocou nao contam como mudanca do Linear na proxima rodada.
        finished = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") if pending else started
        STATE.parent.mkdir(exist_ok=True)
        hashes = {b["id"]: fingerprint(b) for b in current if b["status"] != "closed" or "linear.app" in (b.get("external_ref") or "")}
        STATE.write_text(json.dumps({"last_sync": finished, "hashes": hashes}, indent=1))


if __name__ == "__main__":
    main()
