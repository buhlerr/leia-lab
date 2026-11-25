"""Regras determinísticas do domínio de minutas (LeiaFicha, LeiaTriar, LeiaValidar).

Porte, sem dependências externas, da lógica de ``deploy_agente.py``. Nenhuma
função registra texto de minuta em logs ou mensagens de exceção.
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

DATA_RE = re.compile(
    r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{1,2}º?\s+de\s+[a-zçã]+\s+de\s+\d{4}\b",
    re.I,
)
PRAZO_RE = re.compile(r"\b\d{1,3}\s*(?:\([^)]{1,30}\))?\s*mes(?:es)?\b", re.I)
VALOR_RE = re.compile(r"R\$\s*[\d.]+(?:,\d{2})?")


def _candidates(rx: re.Pattern[str], text: str, limit: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in rx.finditer(text):
        v = m.group(0)
        if v.lower() in seen:
            continue
        seen.add(v.lower())
        out.append((v, text[max(0, m.start() - 90) : m.end() + 60]))
        if len(out) >= limit:
            break
    return out


def extract_ficha_candidates(text: str, limit: int = 14) -> dict[str, list[tuple[str, str]]]:
    """Candidatos (valor, contexto) de datas, prazos e valores da ficha."""
    t = re.sub(r"\s+", " ", text or "")
    return {
        "datas": _candidates(DATA_RE, t, limit),
        "prazos": _candidates(PRAZO_RE, t, limit),
        "valores": _candidates(VALOR_RE, t, limit),
    }


_HEADER_RE = re.compile(
    r"(?i)(?=\b(?:cl[áa]usula\s+(?:\d+|[a-zà-ÿ]+)[ªºa°]?(?:\s+[a-zà-ÿ]+)?\s*(?:[-–—:.]|\s))"
    r"|(?<![\d.,])\b\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\.?\s+(?=[A-ZÀ-Ý]))"
)
_LINE_HEADER_RE = re.compile(
    r"(?im)(?=(?:^|\n)[ \t]*(?:cl[áa]usula\s+(?:\d+|[a-zà-ÿ]+)[ªºa°]?(?:\s+[a-zà-ÿ]+)?\s*(?:[-–—:.]|\s|$)"
    r"|\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\.?\s+(?=[A-ZÀ-Ý])))"
)
_MIN_CLAUSE = 120
_MAX_CLAUSE = 1800


def segment_clauses(text: str) -> list[str]:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n" in raw:
        parts = [re.sub(r"\s+", " ", x).strip() for x in _LINE_HEADER_RE.split(raw) if x and x.strip()]
    else:
        t = re.sub(r"\s+", " ", raw).strip()
        parts = [x.strip() for x in _HEADER_RE.split(t) if x and x.strip()]
    merged: list[str] = []
    buf = ""
    for part in parts:
        buf = (buf + " " + part).strip()
        if len(buf) >= _MIN_CLAUSE:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    final: list[str] = []
    for p in merged:
        while len(p) > _MAX_CLAUSE:
            i = p.rfind(". ", 600, _MAX_CLAUSE)
            i = i + 1 if i > 0 else _MAX_CLAUSE
            final.append(p[:i].strip())
            p = p[i:].strip()
        final.append(p)
    return final


DEFAULT_TEMAS: list[str] = [
    "benfeitorias_e_conservacao",
    "foro_processo_e_arbitragem",
    "garantias_locaticias",
    "multa_e_rescisao",
    "obrigo_e_encargos",
    "reajuste_e_indexacao",
]

DEFAULT_RISCOS: dict[str, list[dict[str, Any]]] = {
    "reajuste_e_indexacao": [
        {
            "id": "R-01",
            "risco": "Periodicidade de reajuste inferior a 1 ano",
            "cor": "vermelho",
            "parte": "locatario",
            "normas": [{"id": "lei-10192-2001-art-2", "citacao": "Lei 10.192/2001, art. 2"}],
        }
    ],
    "garantias_locaticias": [
        {
            "id": "R-02",
            "risco": "Cumulação de modalidades de garantia",
            "cor": "vermelho",
            "parte": "locatario",
            "normas": [{"id": "lei-8245-1991-art-37", "citacao": "Lei 8.245/1991, art. 37"}],
        }
    ],
    "multa_e_rescisao": [
        {
            "id": "R-03",
            "risco": "Multa rescisória sem proporcionalidade ao prazo cumprido",
            "cor": "amarelo",
            "parte": "locatario",
            "normas": [{"id": "lei-8245-1991-art-4", "citacao": "Lei 8.245/1991, art. 4"}],
        }
    ],
    "benfeitorias_e_conservacao": [
        {
            "id": "R-04",
            "risco": "Renúncia antecipada à indenização por benfeitorias necessárias",
            "cor": "amarelo",
            "parte": "locatario",
            "normas": [{"id": "lei-8245-1991-art-35", "citacao": "Lei 8.245/1991, art. 35"}],
        }
    ],
    "foro_processo_e_arbitragem": [
        {
            "id": "R-05",
            "risco": "Foro de eleição distante do imóvel",
            "cor": "verde",
            "parte": "locatario",
            "normas": [],
        }
    ],
    "obrigo_e_encargos": [
        {
            "id": "R-06",
            "risco": "Transferência de encargos de responsabilidade do locador",
            "cor": "amarelo",
            "parte": "locatario",
            "normas": [{"id": "lei-8245-1991-art-22", "citacao": "Lei 8.245/1991, art. 22"}],
        }
    ],
}

DEFAULT_TEMA_MAP: dict[str, list[str]] = {
    "reajuste_e_indexacao": ["lei-10192-2001-art-2"],
    "garantias_locaticias": ["lei-8245-1991-art-37"],
    "multa_e_rescisao": ["lei-8245-1991-art-4"],
    "benfeitorias_e_conservacao": ["lei-8245-1991-art-35"],
    "foro_processo_e_arbitragem": [],
    "obrigo_e_encargos": ["lei-8245-1991-art-22"],
}


def citacao_de(norma: str, artigo: Any = None) -> str:
    """``{norma, artigo}`` da matriz real -> a citacao usada no relatorio e como titulo na base."""
    art = str(artigo or "").strip()
    return f"{norma.strip()}, art. {art}" if art else norma.strip()


def norm_slug(citacao: str) -> str:
    """Id estavel de uma citacao: ``Lei 8.245/1991, art. 35`` -> ``lei-8245-1991-art-35``."""
    s = unicodedata.normalize("NFKD", citacao).encode("ascii", "ignore").decode()
    s = re.sub(r"(?<=\d)\.(?=\d)", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def normalize_norm(
    n: Any, *, risk_id: str = "?", kb_ids: dict[str, str] | None = None
) -> dict[str, Any]:
    """Uma norma da matriz -> ``{"id", "citacao", ...extras}`` (bead leia-lab-vz3).

    Aceita os dois formatos: ``{citacao, id?}`` (padrao) e ``{norma, artigo, status, por_que}``
    (matriz real). Os extras ficam. ``kb_ids`` (citacao -> id na base normativa) da o id da
    base quando a norma tem texto la. Norma que nao da para mapear LEVANTA erro: antes ela era
    descartada em silencio e todo risco vermelho caia para amarelo.
    """
    if not isinstance(n, dict):
        raise ValueError(f"risco {risk_id}: norma nao e objeto")
    if n.get("citacao"):
        citacao = str(n["citacao"]).strip()
    elif n.get("norma"):
        citacao = citacao_de(n["norma"], n.get("artigo"))
    else:
        raise ValueError(f"risco {risk_id}: norma sem 'citacao' nem 'norma' (chaves={sorted(n)})")
    out = {k: v for k, v in n.items() if k not in {"id", "citacao"}}
    out["id"] = n.get("id") or (kb_ids or {}).get(citacao) or norm_slug(citacao)
    out["citacao"] = citacao
    return out


def parse_matrix_line(r: dict[str, Any], kb_ids: dict[str, str] | None = None) -> dict[str, Any]:
    """Uma linha do JSONL da matriz -> risco no formato do grafo (``id, risco, cor, parte, normas``)."""
    return {
        "id": r["id"],
        "risco": r["risco"],
        "cor": r["criticidade_sugerida"],
        "parte": r["parte_prejudicada"],
        "normas": [normalize_norm(n, risk_id=r["id"], kb_ids=kb_ids) for n in r.get("normas", [])],
    }


def load_risk_matrix(
    matrix_path: Path | None = None,
) -> tuple[list[str], dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """Carrega ``(temas, riscos, tema_map)`` de um JSONL; sem arquivo, usa o padrão embutido.

    Cada linha: ``id``, ``tema``, ``risco``, ``criticidade_sugerida``, ``parte_prejudicada`` e
    ``normas`` (``{citacao, id?}`` ou ``{norma, artigo, ...}``; ver ``normalize_norm``).
    """
    if matrix_path is None or not Path(matrix_path).is_file():
        return list(DEFAULT_TEMAS), {k: list(v) for k, v in DEFAULT_RISCOS.items()}, {
            k: list(v) for k, v in DEFAULT_TEMA_MAP.items()
        }
    riscos: dict[str, list[dict[str, Any]]] = {}
    tema_map: dict[str, list[str]] = {}
    for line in Path(matrix_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        risco = parse_matrix_line(r)
        riscos.setdefault(r["tema"], []).append(risco)
        ids = tema_map.setdefault(r["tema"], [])
        for n in risco["normas"]:
            if n["id"] not in ids:
                ids.append(n["id"])
    return sorted(riscos), riscos, tema_map


_COR = {"vermelho": "red", "amarelo": "yellow", "verde": "green"}
_ROTULO = {"red": "VERMELHO", "yellow": "AMARELO", "green": "VERDE"}
_ORDEM = {"red": 0, "yellow": 1, "green": 2}


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def validate_and_format(doc_state: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Valida alertas e devolve ``(relatório_markdown, envelope, diagnóstico)``."""
    d = dict(doc_state)
    trilha: list[dict[str, Any]] = []

    def reg(cl: dict[str, Any], resultado: str, motivo: str, validacao: dict[str, Any] | None = None) -> None:
        trilha.append(
            {
                "n": cl["n"],
                "texto": cl["texto"],
                "triagem": {"risco": cl.get("risco"), "tema": cl.get("tema")},
                "checks": cl.get("checks", []),
                "confirmados": [x["id"] for x in cl.get("confirmados", [])],
                "candidatas": cl.get("candidatas", []),
                "normas": [
                    {"citacao": n["citacao"], "nota": n.get("nota"), "origem": n.get("origem")}
                    for n in cl.get("normas", [])
                ],
                "analise_bruta": cl.get("analise_bruta"),
                "validacao": validacao or {},
                "resultado": resultado,
                "motivo": motivo,
            }
        )

    stats = d.get("stats") or {}
    env: dict[str, Any] = {
        "schema_version": 1,
        "minuta_id": d.get("filename"),
        "type": "alerts",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "minuta_type": d.get("tipo"),
        "score_tipo": d.get("score_tipo"),
        "ficha": d.get("ficha"),
        "stats": stats,
    }
    if not d.get("suportado"):
        env.update(
            {
                "status": "unsupported",
                "content": {"alerts": []},
                "remarks": ["Tipo de minuta nao suportado. O fluxo foi interrompido."],
            }
        )
        texto = "Tipo de minuta nao suportado. Fluxo interrompido."
    else:
        alertas: list[dict[str, Any]] = []
        ajustes = {"trecho_nao_literal": 0, "sem_redacao": 0, "discordancias_redator": 0, "rebaixados_sem_norma": 0}
        for cl in d.get("clausulas") or []:
            conf = cl.get("confirmados") or []
            if not conf:
                reg(cl, "descartada", "nenhum_risco_da_matriz")
                continue
            analise = cl.get("analise") or {}
            por_id = {x.get("id"): x for x in (analise.get("alertas") or []) if isinstance(x, dict)}
            cores: list[str] = []
            for x in conf:
                w = por_id.get(x["id"])
                if w is None:
                    ajustes["sem_redacao"] += 1
                    w = {}
                cor = _COR.get(x["cor"], "yellow")
                basis = [n["citacao"] for n in x.get("normas", [])]
                rebaixado = not basis and cor == "red"
                if rebaixado:
                    cor = "yellow"
                    ajustes["rebaixados_sem_norma"] += 1
                trecho = w.get("trecho") or ""
                literal = bool(trecho) and _norm(trecho) in _norm(cl["texto"])
                if not literal:
                    ajustes["trecho_nao_literal"] += 1
                    trecho = cl["texto"][:240]
                if w.get("discorda"):
                    ajustes["discordancias_redator"] += 1
                cores.append(cor)
                alertas.append(
                    {
                        "severity": cor,
                        "risk_id": x["id"],
                        "excerpt": trecho,
                        "excerpt_literal": literal,
                        "summary": w.get("resumo") or x["risco"],
                        "detail": w.get("detalhe")
                        or "Explicacao automatica indisponivel. Risco identificado pela matriz.",
                        "risk": x["risco"],
                        "legal_basis": basis,
                        "party": x.get("parte"),
                        "theme": cl.get("tema"),
                        "clause_index": cl["n"],
                        "confirmation_score": x.get("noul"),
                        "writer_disagrees": bool(w.get("discorda")),
                        **(
                            {"downgraded": "vermelho -> amarelo: o risco nao tem norma na matriz que o fundamente"}
                            if rebaixado
                            else {}
                        ),
                    }
                )
            reg(cl, "alerta", sorted(cores, key=_ORDEM.__getitem__)[0], {"riscos": [x["id"] for x in conf]})
        alertas.sort(key=lambda a: (_ORDEM[a["severity"]], a["clause_index"]))
        c = {k: sum(1 for a in alertas if a["severity"] == k) for k in _ORDEM}
        obs = [
            "Resultado de apoio: a revisao humana continua obrigatoria.",
            "A criticidade vem da matriz de riscos, ainda nao validada por advogado.",
        ]
        if stats.get("nao_redigidas"):
            obs.append(f"{stats['nao_redigidas']} clausulas ficaram sem redacao por causa do limite.")
        if stats.get("sem_orcamento"):
            obs.append(f"{stats['sem_orcamento']} clausulas ficaram sem redacao: o teto de custo por analise foi atingido.")
        if stats.get("falhas_redacao"):
            obs.append(f"{stats['falhas_redacao']} clausulas falharam na redacao.")
        env.update(
            {
                "status": "done",
                "content": {"alerts": alertas, "counts": c, "ajustes_validacao": ajustes},
                "remarks": obs,
            }
        )
        nl = "\n"
        linhas = [
            f"Tipo: {d.get('tipo')} ({d.get('score_tipo') or 0:.2f}). "
            f"Vermelhos: {c['red']}, amarelos: {c['yellow']}, verdes: {c['green']}.",
            "",
        ] + [
            f"[{_ROTULO[a['severity']]}] {a['summary']}"
            + nl
            + f"Trecho: {a['excerpt']}"
            + nl
            + (f"Fundamento: {', '.join(a['legal_basis'])}" + nl if a["legal_basis"] else "")
            + a["detail"]
            + nl
            for a in alertas
        ]
        texto = nl.join(linhas + obs)

    funil: dict[str, int] = {}
    for x in trilha:
        funil[x["motivo"]] = funil.get(x["motivo"], 0) + 1
    diag = {
        "minuta_id": d.get("filename"),
        "tipo": d.get("tipo"),
        "ficha": d.get("ficha"),
        "ficha_confianca": d.get("ficha_confianca"),
        "stats": stats,
        "funil": funil,
        "clausulas": trilha,
    }
    report = texto + "\n\n```json\n" + json.dumps(env, ensure_ascii=False) + "\n```"
    return report, env, diag
