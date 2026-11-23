"""Coloca no projeto do Linear deste repo toda issue ligada a um bead que ainda esta sem projeto.

O `bd linear sync` nao sabe de projetos: so cria a issue no time. Uso (scripts/linear-sync.sh):
    bd list --all --json | python3 scripts/linear_project.py leia-lab [--dry-run]
Precisa de LINEAR_API_KEY (via `op run --env-file=.env.op`).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

API = "https://api.linear.app/graphql"
USER_AGENT = "leia-lab-linear-sync (+https://github.com/buhlerr/leia-lab)"
_IDENT = re.compile(r"linear\.app/[^/]+/issue/([A-Z]+-\d+)")


def gql(query: str, variables: dict | None = None) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Authorization": os.environ["LINEAR_API_KEY"],
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise SystemExit(f"Linear: {body['errors']}")
    return body["data"]


def main() -> None:
    project_name, dry_run = sys.argv[1], "--dry-run" in sys.argv[2:]
    linked = {m.group(1) for b in json.load(sys.stdin) if (m := _IDENT.search(b.get("external_ref") or ""))}
    projects = gql("query($n: String!) { projects(filter: {name: {eq: $n}}) { nodes { id } } }", {"n": project_name})
    if not projects["projects"]["nodes"]:
        raise SystemExit(f"Linear: projeto {project_name!r} nao existe; crie-o no time antes de sincronizar")
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

    for issue in loose:
        if not dry_run:
            gql(
                "mutation($id: String!, $p: String!) { issueUpdate(id: $id, input: {projectId: $p}) { success } }",
                {"id": issue["id"], "p": project_id},
            )
    verb = "iria para" if dry_run else "foi para"
    print(f"{len(loose)} issue(s) {verb} o projeto {project_name}: {', '.join(sorted(i['identifier'] for i in loose)) or '-'}")


if __name__ == "__main__":
    main()
