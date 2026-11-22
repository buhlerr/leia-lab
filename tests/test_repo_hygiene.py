"""O que o .gitignore exclui nao pode estar versionado (5c32d0a versionou 3.918 arquivos de node_modules)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = REPO) -> list[str]:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def tracked_but_ignored(cwd: Path = REPO, gitignore: Path = REPO / ".gitignore") -> list[str]:
    return _git("ls-files", "--cached", "--ignored", f"--exclude-from={gitignore}", cwd=cwd)


def orphan_gitlinks(cwd: Path = REPO) -> list[str]:
    if (cwd / ".gitmodules").exists():
        return []
    return [line.split("\t", 1)[1] for line in _git("ls-files", "--stage", cwd=cwd) if line.startswith("160000 ")]


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
