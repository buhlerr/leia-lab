"""Versoes de dados do repo (``data/``) aplicadas no banco: matriz real e base normativa (M5, Q5).

Decisao Q5 (opcao A): cada versao e um arquivo IMUTAVEL no repo com sha256 no manifesto. Ela entra
no banco uma vez so (ledger ``data_versions``) e, dali em diante, o banco e a fonte da verdade:
quem nao programa edita pelo admin e cada edicao fica no ``domain_history``. Uma versao nova
(``v2``) e um arquivo novo; nunca se reescreve uma versao publicada.

* ``apply_base``: indexa cada artigo da base normativa como um ``kb_docs`` cujo titulo e a citacao
  (``Lei 8.245/1991, art. 35``), que e como o grafo de analise acha o texto da norma.
* ``apply_matrix``: desativa (sem apagar) os riscos ativos do tipo e grava os da versao. Normas sao
  normalizadas por ``normalize_norm`` (bead leia-lab-vz3): nenhuma e descartada em silencio.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncpg

from src.db.defaults import LOCACAO_RESIDENCIAL
from src.graphs.minuta_rules import citacao_de, parse_matrix_line

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class DataVersionError(RuntimeError):
    """Versao de dado ausente, adulterada ou em conflito com o que o banco ja registrou."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _combined(hashes: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


# --- leitura (pura, sem banco) -------------------------------------------------


def read_base(version: str = "v1", data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], str]:
    """Artigos da base normativa (``citacao``, ``id``, ``texto``, ``fonte``...) e o sha256 da versao."""
    d = data_dir / "base-normativa" / version
    manifest_path = d / "MANIFEST.json"
    if not manifest_path.is_file():
        raise DataVersionError(f"base-normativa/{version}: sem MANIFEST.json")
    files: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))["arquivos"]
    artigos: list[dict[str, Any]] = []
    for name, expected in sorted(files.items()):
        p = d / name
        if not p.is_file() or _sha(p) != expected:
            raise DataVersionError(f"base-normativa/{version}/{name}: arquivo ausente ou sha256 diferente do manifesto")
        for a in _jsonl(p):
            artigos.append({**a, "citacao": citacao_de(a["norma"], a.get("artigo"))})
    dup = len(artigos) - len({a["citacao"] for a in artigos})
    if dup:
        raise DataVersionError(f"base-normativa/{version}: {dup} citacoes repetidas")
    return artigos, _combined(files)


def read_matrix(
    version: str = "v1", data_dir: Path = DATA_DIR, kb_ids: dict[str, str] | None = None
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    """``[(tema, risco), ...]`` na ordem do arquivo e o sha256 conferido com o manifesto."""
    manifest_path = data_dir / "matriz" / f"{version}.manifest.json"
    if not manifest_path.is_file():
        raise DataVersionError(f"matriz/{version}: sem manifesto")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    p = data_dir / "matriz" / manifest["arquivo"]
    if not p.is_file() or _sha(p) != manifest["sha256"]:
        raise DataVersionError(f"matriz/{version}: arquivo ausente ou sha256 diferente do manifesto")
    rows = [(r["tema"], parse_matrix_line(r, kb_ids)) for r in _jsonl(p)]
    ids = [x["id"] for _, x in rows]
    if len(ids) != len(set(ids)):
        raise DataVersionError(f"matriz/{version}: ids de risco repetidos")
    return rows, manifest["sha256"]


# --- ledger -----------------------------------------------------------------------


async def _already_applied(conn: asyncpg.Connection, name: str, sha: str) -> bool:
    recorded = await conn.fetchval("SELECT sha256 FROM data_versions WHERE name = $1", name)
    if recorded is None:
        return False
    if recorded != sha:
        raise DataVersionError(
            f"{name} ja foi aplicada com outro conteudo (sha {recorded[:12]} no banco, {sha[:12]} no repo): "
            "versao publicada nao muda; crie uma versao nova"
        )
    return True


async def applied_versions(pool: asyncpg.Pool) -> dict[str, str]:
    return {r["name"]: r["sha256"] for r in await pool.fetch("SELECT name, sha256 FROM data_versions ORDER BY name")}


# --- base normativa ---------------------------------------------------------------

IngestFn = Callable[[str, str, str], Awaitable[Any]]  # (texto, citacao, source)


async def apply_base(pool: asyncpg.Pool, ingest_fn: IngestFn, version: str = "v1", data_dir: Path = DATA_DIR) -> int:
    """Indexa os artigos que faltam e registra a versao. Retomavel: artigo ja indexado e pulado.

    ``ingest_fn`` e o grafo de ingestao (mascara + embedding + gravacao); ver ``src.cli``.
    Devolve quantos artigos foram indexados nesta chamada.
    """
    name = f"base-normativa/{version}"
    artigos, sha = read_base(version, data_dir)
    async with pool.acquire() as conn:
        if await _already_applied(conn, name, sha):
            return 0
        have = {
            r["title"]
            for r in await conn.fetch("SELECT title FROM kb_docs WHERE source = $1", name)
        }
    novos = [a for a in artigos if a["citacao"] not in have]
    for a in novos:
        await ingest_fn(a["texto"], a["citacao"], name)
    async with pool.acquire() as conn, conn.transaction():
        n = await conn.fetchval(
            "SELECT count(DISTINCT title) FROM kb_docs WHERE source = $1 AND title = ANY($2::text[])",
            name,
            [a["citacao"] for a in artigos],
        )
        if n != len(artigos):
            raise DataVersionError(f"{name}: {len(artigos) - n} artigos sem indexar; rode de novo")
        if not await _already_applied(conn, name, sha):
            await conn.execute("INSERT INTO data_versions (name, sha256) VALUES ($1, $2)", name, sha)
    return len(novos)


# --- matriz -------------------------------------------------------------------------


async def apply_matrix(
    pool: asyncpg.Pool,
    version: str = "v1",
    data_dir: Path = DATA_DIR,
    *,
    base_version: str = "v1",
    type_slug: str = LOCACAO_RESIDENCIAL,
) -> bool:
    """Troca a matriz ativa do tipo pela versao do repo, numa transacao. ``False`` se ja aplicada.

    Os riscos anteriores ficam ``active = false`` (nada e apagado; o ``domain_history`` registra a
    troca e as analises antigas guardam sua propria foto). Temas novos sao criados; os que ja
    existem so mudam de posicao. Exige o tipo ja semeado (``seed_defaults``: tipo e prompts).
    """
    name = f"matriz/{version}"
    ids = {a["citacao"]: a["id"] for a in read_base(base_version, data_dir)[0]}
    rows, sha = read_matrix(version, data_dir, kb_ids=ids)
    async with pool.acquire() as conn, conn.transaction():
        if await _already_applied(conn, name, sha):
            return False
        type_id = await conn.fetchval("SELECT id FROM minuta_types WHERE slug = $1", type_slug)
        if type_id is None:
            raise DataVersionError(f"tipo {type_slug!r} nao existe: rode init (seed_defaults) antes")
        await conn.execute(
            "UPDATE risk_matrix SET active = false WHERE active AND theme_id IN "
            "(SELECT id FROM themes WHERE minuta_type_id = $1)",
            type_id,
        )
        theme_ids: dict[str, int] = {}
        for tema, _ in rows:
            if tema in theme_ids:
                continue
            theme_ids[tema] = await conn.fetchval(
                "INSERT INTO themes (minuta_type_id, slug, position) VALUES ($1, $2, $3) "
                "ON CONFLICT (minuta_type_id, slug) DO UPDATE SET position = EXCLUDED.position RETURNING id",
                type_id,
                tema,
                len(theme_ids),
            )
        await conn.executemany(
            "INSERT INTO risk_matrix (theme_id, risk_id, description, criticality, party, norms) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            [
                (theme_ids[tema], x["id"], x["risco"], x["cor"], x["parte"], json.dumps(x["normas"], ensure_ascii=False))
                for tema, x in rows
            ],
        )
        await conn.execute("INSERT INTO data_versions (name, sha256) VALUES ($1, $2)", name, sha)
    return True
