"""Higiene do repo em si, nao do codigo.

Duas avarias reais que viraram checagem: o .gitignore exclui arquivos que
5c32d0a versionou, e *.md versionado cita caminho que nao existe (a ADR-0002
citava `src/tracing/`, que so existiu em branch de prototipo). A frase falsa
"the minutas are absent" do AGENTS.md era fato sobre a maquina, nao caminho:
fora do alcance desta checagem.
"""

from __future__ import annotations

import posixpath
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args: str, cwd: Path = REPO) -> list[str]:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def _git_z(*args: str, cwd: Path = REPO) -> list[str]:
    """Saida do git separada por byte nulo: nome com acento ou escape de
    core.quotepath nao passa por aqui, so o caminho bruto."""
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


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
# bd gere (.beads/) e a pesquisa de frameworks, que cita caminho de outro
# checkout (acornworm, kb-legislacao), nao afirmacao sobre esta arvore. So o
# arquivo da pesquisa fica fora; outro *.md que entrar em docs/research/ e
# checado como qualquer doc.
NOT_REPO_DOCS = (
    ".agents/",
    ".beads/",
    ".commandcode/",
    "docs/research/2026-11-framework-evaluation.md",
)

# Git-ignored citado de proposito: existe so na maquina que o usa, por design.
CITED_IGNORED_ROOTS = (".local", ".planning", "leia-kb-legislacao", "leia-minutas-teste-mascaradas", ".venv")

# Export passivo do bd, citado no bloco que ele mesmo escreve no AGENTS.md.
BD_EXPORTS = (".beads/issues.jsonl",)

BACKTICK = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCED = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
# Placeholder, glob, variavel, ancora, porta, drive, contrabarra, espaco ou
# elipse: nenhum caminho de repo carrega isso.
NOT_A_PATH = re.compile(r"[<>{}*$|:#\\\s…]")


def tracked_paths(cwd: Path = REPO) -> set[str]:
    """Caminho de cada arquivo do indice, com a caixa exata com que o git o
    versiona (ls-files -z): a unica verdade, igual em NTFS, macOS ou Linux."""
    return set(_git_z("ls-files", "--cached", "-z", cwd=cwd))


def base_paths(cwd: Path = REPO) -> set[str]:
    """Arquivos das arvores de onde o HEAD saiu: os pais dele e, quando ha
    origin/master, a do merge-base.

    Um token que sumiu da arvore atual so e reconhecivel como caminho porque
    existia aqui: rename/apagar de entrada de topo (git mv scripts tools)
    deixaria de ser lido como caminho, e a citacao seguiria apontando o nome
    velho sem denuncia. O pai imediato cobre o rename no ultimo commit; o
    merge-base, o rename antigo no meio do branch (no repo real o rename nunca
    e o commit da vez).
    """
    shas = _git("rev-list", "--parents", "-n", "1", "HEAD", cwd=cwd)[0].split()[1:]
    has_master = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/remotes/origin/master"],
        cwd=cwd, capture_output=True, check=False,
    ).returncode == 0
    if has_master:
        shas.append(_git("merge-base", "origin/master", "HEAD", cwd=cwd)[0])
    files: set[str] = set()
    for sha in shas:
        files.update(_git_z("ls-tree", "-r", "--name-only", "-z", sha, cwd=cwd))
    return files


def doc_files(cwd: Path = REPO) -> list[str]:
    """*.md versionados que afirmam algo sobre esta arvore."""
    return [
        p for p in _git_z("ls-files", "--cached", "-z", cwd=cwd)
        if p.endswith(".md") and not p.startswith(NOT_REPO_DOCS)
    ]


def resolves(files: set[str], path: str) -> bool:
    """Existe na arvore: arquivo exato ou diretorio com esse prefixo."""
    return path in files or any(f.startswith(path + "/") for f in files)


def broken_cited_paths(cwd: Path = REPO) -> list[tuple[str, str]]:
    """(doc, caminho) citado em prosa versionada que nao existe no indice.

    Existencia e conferida contra o indice do git, nunca contra o disco: o
    disco mente sobre caixa (NTFS, macOS) e pode nem ser desta maquina.
    Crase e lida relativa a raiz do repo (o padrao de AGENTS.md) ou, em doc
    aninhado, ao diretorio do proprio doc quando o caminho existe la; link e
    relativo ao proprio doc, como o Markdown resolve, e absoluto conta como
    raiz do repo (a leitura do GitHub) ou fica fora, caminho de outra maquina.
    E token que nasce numa raiz atual, ou que existia na arvore de onde o HEAD
    saiu, e caminho de verdade. O allowlist explicito libera o git-ignored citado
    de proposito e o export do bd, que um checkout novo nao tem por design.
    """
    files = tracked_paths(cwd)
    base = base_paths(cwd)
    roots = {p.split("/", 1)[0] for p in files | base}
    roots.update(CITED_IGNORED_ROOTS)
    broken: list[tuple[str, str]] = []
    for rel_md in doc_files(cwd):
        doc_dir = posixpath.dirname(rel_md)
        text = FENCED.sub("", (cwd / rel_md).read_text(encoding="utf-8"))
        for token in BACKTICK.findall(text):
            if NOT_A_PATH.search(token):
                continue
            norm = posixpath.normpath(token)
            if norm.startswith("../"):
                continue
            first = norm.split("/", 1)[0]
            if first in CITED_IGNORED_ROOTS or token in BD_EXPORTS:
                continue
            rel = posixpath.normpath(f"{doc_dir}/{norm}") if doc_dir else norm
            if resolves(files, norm) or (doc_dir and resolves(files, rel)):
                continue
            if resolves(base, norm) or resolves(base, rel) or first in roots:
                broken.append((rel_md, token))
        for target in LINK.findall(text):
            raw = target.split("#", 1)[0]
            if not raw or NOT_A_PATH.search(raw):
                continue
            if raw.startswith("/"):
                resolved = posixpath.normpath(raw.lstrip("/"))
                if resolved.split("/", 1)[0] not in roots:
                    continue
            else:
                resolved = posixpath.normpath(f"{doc_dir}/{raw}" if doc_dir else raw)
            if resolved.startswith("../"):
                continue
            first = resolved.split("/", 1)[0]
            if first in CITED_IGNORED_ROOTS or resolved in BD_EXPORTS:
                continue
            if not resolves(files, resolved):
                broken.append((rel_md, target))
    return broken


def test_no_broken_cited_path_in_docs():
    broken = broken_cited_paths()
    assert not broken, (
        f"{len(broken)} caminho(s) citado(s) em *.md versionado nao existe(m), ex.: {broken[:5]}. "
        "Atualize o doc que cita o caminho movido/apagado; caminho git-ignored citado de proposito "
        "entra na allowlist (CITED_IGNORED_ROOTS / BD_EXPORTS)."
    )


# --- Autotestes em mini-repo: a checagem falha no bug real ---

def _commit(cwd: Path, msg: str) -> None:
    _git("-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", msg, cwd=cwd)


def _commit_all(cwd: Path) -> None:
    """Mini-repo com tudo que esta no disco ja versionado no primeiro commit."""
    _git("init", "-q", cwd=cwd)
    _git("add", ".", cwd=cwd)
    _commit(cwd, "init")


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
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    _git("mv", "src/gone.py", "src/other.py", cwd=tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "src/gone.py")]


def test_top_level_rename_or_delete_breaks_citations(tmp_path: Path):
    """Renomear/apagar entrada de nivel superior (git mv scripts tools, git mv
    deploy infra, git rm pyproject.toml, git mv .env.op .env.1p, git mv gold
    goldset) esconde todas as citacoes do nome velho quando so a arvore ATUAL
    define as raizes. As arvores pai do HEAD continuam com o nome, e sao elas
    que provam que o token era caminho."""
    (tmp_path / "README.md").write_text(
        "Rode `scripts/ci.sh`. Firewall em `deploy/`, build no `pyproject.toml`, "
        "segredos no `.env.op`, gabarito em `gold/gabarito.jsonl`.\n",
        encoding="utf-8",
    )
    for rel in ("scripts/ci.sh", "deploy/firewall.sh", "pyproject.toml", ".env.op", "gold/gabarito.jsonl"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    _git("mv", "scripts", "tools", cwd=tmp_path)
    _git("mv", "deploy", "infra", cwd=tmp_path)
    _git("rm", "-q", "pyproject.toml", cwd=tmp_path)
    _git("mv", ".env.op", ".env.1p", cwd=tmp_path)
    _git("mv", "gold", "goldset", cwd=tmp_path)
    _commit(tmp_path, "mv")
    assert broken_cited_paths(cwd=tmp_path) == [
        ("README.md", "scripts/ci.sh"),
        ("README.md", "deploy/"),
        ("README.md", "pyproject.toml"),
        ("README.md", ".env.op"),
        ("README.md", "gold/gabarito.jsonl"),
    ]


def test_top_level_rename_in_older_commit_still_flagged(tmp_path: Path):
    """No repo real o rename nao e o commit da vez: os pais imediatos do HEAD
    ja tem o nome novo e nao denunciam nada. E a arvore do ponto de saida
    (merge-base com origin/master) que mantem o nome velho reconhecivel."""
    (tmp_path / "README.md").write_text("Rode `scripts/ci.sh`.\n", encoding="utf-8")
    ci = tmp_path / "scripts"
    ci.mkdir()
    (ci / "ci.sh").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path)
    _git("update-ref", "refs/remotes/origin/master", "HEAD", cwd=tmp_path)
    _git("checkout", "-b", "feat", cwd=tmp_path)
    _git("mv", "scripts", "tools", cwd=tmp_path)
    _commit(tmp_path, "mv")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    _git("add", "docs", cwd=tmp_path)
    _commit(tmp_path, "unrelated")
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "scripts/ci.sh")]


def test_citation_case_must_match_the_tracked_path(tmp_path: Path):
    """Em NTFS/macOS o disco resolve `docs/operacao.md` para o arquivo de outra
    caixa e a citacao quebrada passa. O arquivo solto no disco simula o que um
    filesystem case-insensitive faz de graca; a verdade e a caixa do caminho
    versionado no indice, nao a do disco."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "OPERACAO.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Certo: `docs/OPERACAO.md`. Errado: `docs/operacao.md`.\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)
    (tmp_path / "docs" / "operacao.md").write_text("x\n", encoding="utf-8")
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "docs/operacao.md")]


def test_citation_with_accents_matches_tracked_name(tmp_path: Path):
    """Com core.quotepath no default, `git ls-files` devolveria o nome com
    escapes ("rel\\303\\241rio.md") e nenhum caminho com acento seria achado.
    A conferencia le o caminho bruto do indice (ls-files -z)."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "relatório-2026.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Doc: `docs/relatório-2026.md`.\n", encoding="utf-8")
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []


def test_absolute_link_is_read_against_the_repo_root(tmp_path: Path):
    """Link absoluto de producao (`/root/leia/api.env`) fazia Path.exists
    levantar PermissionError: crash no lugar de falha. Absoluto so e afirmacao
    sobre esta arvore quando nasce numa raiz do repo (leitura de raiz do
    GitHub); fora disso e caminho de outra maquina e fica fora."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "OPERACAO.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Producao: [api](/root/leia/api.env). Interno: [op](/docs/OPERACAO.md).\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    (tmp_path / "README.md").write_text("Quebrado: [gone](/docs/nao-existe.md).\n", encoding="utf-8")
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "/docs/nao-existe.md")]


def test_nested_doc_relative_citation(tmp_path: Path):
    """Doc aninhado cita caminho relativo a si (`matriz/v3.jsonl` em
    data/README.md): o primeiro segmento nao e raiz e a citacao nem entrava na
    checagem. Resolve contra o diretorio do doc, e o nome que existia na arvore
    pai prova que era caminho quando quebra."""
    matriz = tmp_path / "data" / "matriz"
    matriz.mkdir(parents=True)
    (matriz / "v3.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "data" / "README.md").write_text("Matriz ativa: `matriz/v3.jsonl`.\n", encoding="utf-8")
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    _git("mv", "data/matriz", "data/matrix", cwd=tmp_path)
    _commit(tmp_path, "mv")
    assert broken_cited_paths(cwd=tmp_path) == [("data/README.md", "matriz/v3.jsonl")]


def test_renamed_or_miscased_link_target_is_flagged(tmp_path: Path):
    """Alem do token em crase, o ALVO de link renomeado ou com caixa trocada
    tem de ser denunciado (a caixa vale igual para link)."""
    model = tmp_path / "model"
    model.mkdir()
    (model / "Lifecycle.tla").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Modelo: [spec](model/Lifecycle.tla).\n", encoding="utf-8")
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
    _git("mv", "model/Lifecycle.tla", "model/Outra.tla", cwd=tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "model/Lifecycle.tla")]
    (tmp_path / "README.md").write_text("Modelo: [spec](model/outra.tla).\n", encoding="utf-8")
    assert broken_cited_paths(cwd=tmp_path) == [("README.md", "model/outra.tla")]


def test_allowlisted_roots_do_not_need_to_exist(tmp_path: Path):
    """A allowlist e o contrato do que e citado de proposito sem existir num
    checkout novo; a checagem nao pode passar a exigir esses caminhos."""
    (tmp_path / "README.md").write_text(
        "Minutas: `leia-minutas-teste-mascaradas/locacao-01.txt`; estado: "
        "`.local/linear-sync-state.json`; plano: `.planning/reviews/pr53.md`.\n",
        encoding="utf-8",
    )
    _commit_all(tmp_path)
    assert broken_cited_paths(cwd=tmp_path) == []
