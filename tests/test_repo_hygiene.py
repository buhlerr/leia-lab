"""Higiene do repo em si, nao do codigo.

Duas avarias reais que viraram checagem: o .gitignore exclui arquivos que
5c32d0a versionou, e *.md versionado cita caminho que nao existe (o AGENTS.md
dizia que as minutas "are absent" na VPS; a ADR-0002 citava `src/tracing/`,
que so existiu em branch de prototipo).
"""

from __future__ import annotations

import re
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


# --- Caminho citado em *.md versionado tem de existir (leia-lab-cxe.13) ---

# Fora da checagem: copias de plugin externo (.agents/, .commandcode/), o que o
# bd gere (.beads/) e snapshot de avaliacao (docs/research/), que cita caminho
# de outro checkout (acornworm, kb-legislacao), nao afirmacao sobre esta arvore.
NOT_REPO_DOCS = (".agents/", ".beads/", ".commandcode/", "docs/research/")

# Git-ignored citado de proposito: existe so na maquina que o usa, por design.
CITED_IGNORED_ROOTS = (".local", ".planning", "leia-kb-legislacao", "leia-minutas-teste-mascaradas", ".venv")

# Export passivo do bd, citado no bloco que ele mesmo escreve no AGENTS.md.
BD_EXPORTS = (".beads/issues.jsonl",)

BACKTICK = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCED = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
FILENAME = re.compile(r"^[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+$")
# Placeholder, glob, variavel, ancora, porta, drive, contrabarra, espaco ou
# elipse: nenhum caminho de repo carrega isso.
NOT_A_PATH = re.compile(r"[<>{}*$|:#\\\s…]")


def doc_files(cwd: Path = REPO) -> list[str]:
    """*.md versionados que afirmam algo sobre esta arvore."""
    return [
        p for p in _git("ls-files", "--cached", cwd=cwd)
        if p.endswith(".md") and not p.startswith(NOT_REPO_DOCS)
    ]


def repo_roots(cwd: Path = REPO) -> set[str]:
    """Entradas de nivel superior versionadas, mais as raizes git-ignored citadas."""
    roots = {p.split("/", 1)[0] for p in _git("ls-files", "--cached", cwd=cwd)}
    roots.update(CITED_IGNORED_ROOTS)
    return roots


def is_cited_repo_path(token: str, roots: set[str]) -> bool:
    """Token entre crases que se le como caminho relativo a raiz do repo.

    Com espaco e comando; com ``<>``/``{}``/``*`` e placeholder ou glob. Sem
    barra, e caminho so se for nome de arquivo com extensao. E o token tem de
    nascer numa entrada de nivel superior do repo: sem isso, caminho de outro
    checkout (acornworm, kb-legislacao) seria lido como afirmacao sobre esta
    arvore.
    """
    if NOT_A_PATH.search(token):
        return False
    if "/" not in token and not FILENAME.match(token):
        return False
    return token.split("/", 1)[0] in roots


def broken_cited_paths(cwd: Path = REPO) -> list[tuple[str, str]]:
    """(doc, caminho) citado em prosa versionada que nao existe na arvore.

    Crase e lida relativa a raiz do repo (o padrao de AGENTS.md); link, relativo
    ao proprio doc, como o Markdown resolve. O allowlist explicito libera o que
    e git-ignored ou gerado pelo bd, que um checkout novo nao tem por design.
    """
    roots = repo_roots(cwd)
    broken: list[tuple[str, str]] = []
    for rel_md in doc_files(cwd):
        text = FENCED.sub("", (cwd / rel_md).read_text(encoding="utf-8"))
        for token in BACKTICK.findall(text):
            if not is_cited_repo_path(token, roots):
                continue
            first = token.split("/", 1)[0]
            if first not in CITED_IGNORED_ROOTS and token not in BD_EXPORTS and not (cwd / token).exists():
                broken.append((rel_md, token))
        for target in LINK.findall(text):
            if NOT_A_PATH.search(target):
                continue
            rel = target.split("#", 1)[0]
            if rel and not (cwd / rel_md).parent.joinpath(rel).exists():
                broken.append((rel_md, target))
    return broken


def test_no_broken_cited_path_in_docs():
    broken = broken_cited_paths()
    assert not broken, (
        f"{len(broken)} caminho(s) citado(s) em *.md versionado nao existe(m), ex.: {broken[:5]}. "
        "Atualize o doc que cita o caminho movido/apagado; caminho git-ignored citado de proposito "
        "entra na allowlist (CITED_IGNORED_ROOTS / BD_EXPORTS)."
    )


def test_broken_cited_paths_flag_a_renamed_file(tmp_path: Path):
    """Renomear um arquivo citado: o detector denuncia o caminho velho no doc."""
    (tmp_path / "README.md").write_text(
        "Entry points: `src/cli.py` and `src/gone.py`. Model: [spec](model/Lifecycle.tla).\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "cli.py").write_text("x = 1\n", encoding="utf-8")
    (src / "gone.py").write_text("x = 1\n", encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "Lifecycle.tla").write_text("x = 1\n", encoding="utf-8")
    _git("init", "-q", cwd=tmp_path)
    _git("add", ".", cwd=tmp_path)
    _git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "init", cwd=tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    _git("mv", "src/gone.py", "src/other.py", cwd=tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "src/gone.py")]
