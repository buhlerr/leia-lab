"""O que o .gitignore exclui nao pode estar versionado (5c32d0a versionou 3.918 arquivos de node_modules)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = REPO) -> list[str]:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def tracked_but_ignored(cwd: Path = REPO, root_rules: Path | None = None) -> list[str]:
    """Versionados que algum .gitignore do repo exclui (o da raiz e os aninhados, ex.: .beads/.gitignore).

    ``root_rules`` aplica as regras de hoje a uma arvore antiga, para reproduzir um commit passado.
    """
    extra = [f"--exclude-from={root_rules}"] if root_rules else []
    return _git("ls-files", "--cached", "--ignored", "--exclude-per-directory=.gitignore", *extra, cwd=cwd)


def orphan_gitlinks(cwd: Path = REPO) -> list[str]:
    declared: set[str] = set()
    if _git("ls-files", ".gitmodules", cwd=cwd):
        out = subprocess.run(
            ["git", "config", "--file", ".gitmodules", "--get-regexp", r"\.path$"],
            cwd=cwd, capture_output=True, text=True, check=False,
        ).stdout
        declared = {line.split(" ", 1)[1] for line in out.splitlines()}
    links = [line.split("\t", 1)[1] for line in _git("ls-files", "--stage", cwd=cwd) if line.startswith("160000 ")]
    return [path for path in links if path not in declared]


def test_no_tracked_file_matches_gitignore():
    paths = tracked_but_ignored()
    assert not paths, (
        f"{len(paths)} arquivo(s) versionado(s) que o .gitignore exclui, ex.: {paths[:5]}. "
        "Rode `git rm -r --cached <caminho>`; o arquivo continua no disco."
    )


def test_no_gitlink_without_gitmodules():
    links = orphan_gitlinks()
    assert not links, (
        f"gitlink sem .gitmodules (outro repo/worktree commitado como pasta): {links}. "
        "Rode `git rm --cached <caminho>` e ponha o caminho no .gitignore."
    )
