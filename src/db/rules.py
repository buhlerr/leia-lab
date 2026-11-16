"""Le as tabelas de dominio numa foto imutavel e com hash: as regras de UMA analise.

A foto e lida numa unica transacao REPEATABLE READ, entao e consistente por dentro. E sobre ela
que o grafo roda (``state["rules"]``) e e ela que fica gravada com a analise: a analise continua
autossuficiente depois que a matriz muda.

As versoes sao hash de conteudo (``matrix_version`` = temas + riscos; ``prompt_version`` =
prompts + descricoes do classificador), entao mudam com QUALQUER escrita, inclusive por psql.
``history_id`` e a marca do ``domain_history`` na leitura: linhas depois dela sao mudancas
feitas depois da analise.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import asyncpg

SCHEMA_VERSION = 1
REQUIRED_PROMPTS = ("redigir_system", "triagem_risco", "confirmar_risco", "regula_norma")


class RulesConfigError(RuntimeError):
    """As regras do banco nao permitem rodar uma analise (tipo sem prompt, nenhum tipo ativo...)."""


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RulesSnapshot:
    content: dict[str, Any]
    hash: str
    matrix_version: str
    prompt_version: str
    history_id: int


def verify_snapshot(content: dict[str, Any], expected_hash: str) -> bool:
    return _sha(content) == expected_hash


def _decode(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _check(types: dict[str, dict[str, Any]]) -> None:
    """Falha alto antes de qualquer chamada externa: nunca cair num prompt padrao em silencio."""
    if not types:
        raise RulesConfigError("nenhum tipo de minuta ativo no banco (rode seed_defaults)")
    for slug, t in types.items():
        missing = [k for k in REQUIRED_PROMPTS if k not in t["prompts"]]
        if missing:
            raise RulesConfigError(f"tipo {slug!r} sem prompt ativo: {', '.join(missing)}")


async def load_rules_snapshot(pool: asyncpg.Pool) -> RulesSnapshot:
    async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
        history_id = await conn.fetchval("SELECT coalesce(max(id), 0) FROM domain_history")
        types = await conn.fetch(
            "SELECT id, slug, name, classifier_description FROM minuta_types WHERE active ORDER BY id"
        )
        themes = await conn.fetch(
            "SELECT id, minuta_type_id, slug, description, norm_ids FROM themes ORDER BY position, id"
        )
        risks = await conn.fetch(
            "SELECT theme_id, risk_id, description, criticality, party, norms FROM risk_matrix "
            "WHERE active ORDER BY id"
        )
        prompts = await conn.fetch(
            "SELECT minuta_type_id, kind, prompt_text, model FROM prompts WHERE active ORDER BY position, id"
        )
    theme_slug = {t["id"]: t["slug"] for t in themes}
    out: dict[str, Any] = {}
    for ty in types:
        # Tema sem nenhum risco ativo fica de fora: nao ha o que confirmar nele (ex.: temas da
        # matriz padrao depois que uma matriz versionada substitui os riscos).
        with_risk = {r["theme_id"] for r in risks}
        mine = [t for t in themes if t["minuta_type_id"] == ty["id"] and t["id"] in with_risk]
        mine_ids = {t["id"] for t in mine}
        riscos: dict[str, list[dict[str, Any]]] = {}
        for r in risks:
            if r["theme_id"] in mine_ids:
                riscos.setdefault(theme_slug[r["theme_id"]], []).append(
                    {
                        "id": r["risk_id"],
                        "risco": r["description"],
                        "cor": r["criticality"],
                        "parte": r["party"],
                        "normas": _decode(r["norms"]),
                    }
                )
        pr: dict[str, dict[str, Any]] = {}
        for p in prompts:
            if p["minuta_type_id"] == ty["id"]:
                pr.setdefault(p["kind"], {"text": p["prompt_text"], "model": p["model"]})  # menor position vence
        out[ty["slug"]] = {
            "name": ty["name"],
            "classifier": ty["classifier_description"],
            "temas": [t["slug"] for t in mine],
            "tema_desc": {t["slug"]: t["description"] for t in mine if t["description"]},
            "tema_map": {t["slug"]: list(t["norm_ids"]) for t in mine},
            "riscos": riscos,
            "prompts": pr,
        }
    _check(out)
    content = {"schema": SCHEMA_VERSION, "history_id": history_id, "types": out}
    matrix = {s: {k: t[k] for k in ("temas", "tema_desc", "tema_map", "riscos")} for s, t in out.items()}
    prompt = {s: {k: t[k] for k in ("classifier", "prompts")} for s, t in out.items()}
    return RulesSnapshot(content, _sha(content), _sha(matrix)[:12], _sha(prompt)[:12], history_id)
