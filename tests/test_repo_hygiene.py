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
    """Gitlinks (mode 160000) que o .gitmodules do INDICE nao declara.

    O .gitmodules e lido do indice (``--blob :.gitmodules``), nao do disco: uma edicao
    local (ou remocao) do arquivo nao pode mascarar nem inventar gitlink orfao.
    """
    declared: set[str] = set()
    if _git("ls-files", ".gitmodules", cwd=cwd):
        out = subprocess.run(
            ["git", "config", "--blob", ":.gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
            cwd=cwd, capture_output=True, text=True, check=False,
        ).stdout
        declared = {line.partition(" ")[2] for line in out.splitlines()}
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


def test_orphan_gitlinks_reads_gitmodules_from_the_index(tmp_path: Path):
    """A guarda le o .gitmodules do INDICE: editar o arquivo no disco nao pode
    mascarar um gitlink orfao nem acusar um declarado (o achado LOW do leia-lab-cxe.4)."""
    gsub = tmp_path / ".gitmodules"
    gsub.write_text('[submodule "x"]\n\tpath = externo\n', encoding="utf-8")
    _git("init", "-q", cwd=tmp_path)
    _git("add", ".gitmodules", cwd=tmp_path)
    _git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "init", cwd=tmp_path)
    empty_tree = subprocess.run(
        ["git", "mktree"], cwd=tmp_path, input="", capture_output=True, text=True, check=True
    ).stdout.strip()
    _git("update-index", "--add", "--cacheinfo", f"160000,{empty_tree},externo", cwd=tmp_path)
    # O disco diverge do indice: declara OUTRO caminho. Lendo o disco (guarda antiga),
    # o gitlink 'externo' apareceria como orfao; pelo indice, esta declarado.
    gsub.write_text('[submodule "x"]\n\tpath = outro\n', encoding="utf-8")
    assert orphan_gitlinks(cwd=tmp_path) == []
    _git("update-index", "--add", "--cacheinfo", f"160000,{empty_tree},nao-declarado", cwd=tmp_path)
    assert orphan_gitlinks(cwd=tmp_path) == ["nao-declarado"]
