"""Grafo LangGraph equivalente a ``LEIA - Analisar Minuta.json``.

``START -> iniciar -> classificar -(suportado)-> ficha -> triar -> buscar -> analisar -> validar -> END``;
minuta nao suportada desvia ``classificar -> validar``.
Texto de minuta nunca entra em logs nem em mensagens de excecao.

Prototype F (bead leia-lab-1g1.9) changes vs master:
* The graph NEVER sees raw text: ``prepare_input`` (used by ``analyze``) reads and masks OUTSIDE the
  graph, so no checkpointer or tracer can export the original text.
* Rules (types, themes, risk matrix, prompts) come from the domain tables as one atomic snapshot read in
  ``iniciar``; that same snapshot is stored with the analysis. No ``DEFAULT_*`` constants are used here.
* Every step appends to the audit trail (``analysis_trail``).
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
import weakref
from collections.abc import AsyncIterator
from functools import wraps
from pathlib import Path
from typing import Any, Literal, TypedDict

import asyncpg
from langgraph.graph import END, START, StateGraph

from src.clients.jev import call_jev
from src.clients.llm import chat_completion
from src.config import Settings
from src.foundation.rules import RulesSnapshot, load_rules_snapshot
from src.foundation.trail import append_trail, finish_analysis, start_analysis
from src.graphs.ingest_graph import _read_path
from src.graphs.minuta_rules import (
    extract_ficha_candidates,
    segment_clauses,
    validate_and_format,
)
from src.ingest.masking import mask_personal_data, resolve_doc_alias
from src.rag.embeddings import EmbeddingResult, embed_text
from src.rag.hybrid_search import hybrid_search_rrf

_EMPTY_TEXT_MSG = "text must be a non-empty string"
_NO_MASKED_TEXT_MSG = "graph input needs masked 'text'; use analyze()/prepare_input() (raw text never enters the graph)"
_CONCURRENCY = 8  # teto global de chamadas externas (Jev, LLM, embeddings) por loop
_EXCERPT = 200  # chars of MASKED clause text kept in the trail

_UNSUPPORTED = "Qualquer outro documento, como lei, codigo, parecer, contrato de outro tipo ou texto sem relacao."
_Q_REGULA_CRITERIA = {
    "true": "O dispositivo trata especificamente do que a clausula regula.",
    "false": "O dispositivo trata apenas de tema parecido.",
}
_Q_RISCO_CRITERIA = {
    "true": "Impoe obrigacao, renuncia, multa, prazo, custo, limitacao de direito ou condicao que pode prejudicar o locatario ou o fiador, mesmo que pareca comum.",
    "false": "E apenas identificacao, descricao do imovel, assinatura ou redacao neutra sem efeito desfavoravel.",
}
_NC = {"nao_consta": "O contrato nao informa isso, ou nenhuma opcao corresponde."}


class AnalyzeMinutaState(TypedDict, total=False):
    # NOTE: no raw_text / file_path here, on purpose (see module docstring).
    filename: str  # public alias, never the real file name
    text: str  # MASKED text
    analysis_id: str
    rules: dict[str, Any]  # rules snapshot content (no personal data)
    rules_meta: dict[str, Any]  # hash, matrix_version, prompt_version, history_id
    tipo: str
    score_tipo: float
    suportado: bool
    ficha: dict[str, Any]
    ficha_confianca: dict[str, Any]
    clausulas: list[dict[str, Any]]
    stats: dict[str, Any]
    report_text: str
    report_envelope: dict[str, Any]
    diagnostics: dict[str, Any]


def route_after_classificar(state: AnalyzeMinutaState) -> Literal["ficha", "validar"]:
    return "ficha" if state.get("suportado") else "validar"


def _choice_question(instr: str, cands: list[tuple[str, str]], extra: dict[str, str]) -> dict[str, Any]:
    crit = {f"c{i}": f"{v}. Contexto: {ctx}" for i, (v, ctx) in enumerate(cands)}
    crit.update(extra)
    return {"type": "choice", "instructions": instr, "criteria": crit}


def _pick(answer: dict[str, Any], cands: list[tuple[str, str]]) -> str:
    c = answer.get("choice", "")
    if re.fullmatch(r"c\d+", c) and int(c[1:]) < len(cands):
        return cands[int(c[1:])][0]
    return c


def _tokens(res: dict[str, Any]) -> int:
    return int((res.get("usage") or {}).get("input_tokens", 0))


async def _gather(coros: list[Any]) -> list[Any]:
    # Sem limite proprio: o teto de concorrencia fica nas chamadas-folha (ver _limiter),
    # senao fan-outs aninhados multiplicariam o limite ou travariam.
    return await asyncio.gather(*coros)


def _type_rules(state: AnalyzeMinutaState) -> dict[str, Any]:
    return state["rules"]["types"][state["tipo"]]


def _prompt(t: dict[str, Any], kind: str) -> dict[str, Any]:
    p = t["prompts"].get(kind)
    if not p:
        raise KeyError(f"prompt kind {kind!r} missing for minuta type")  # a config error, never silently defaulted
    return p


def _snapshot_of(state: AnalyzeMinutaState) -> RulesSnapshot:
    m = state["rules_meta"]
    return RulesSnapshot(state["rules"], m["hash"], m["matrix_version"], m["prompt_version"], m["history_id"])


# ---------------------------------------------------------------- input preparation (outside the graph)
async def prepare_input(
    *, raw_text: str | None = None, file_path: str | Path | None = None, filename: str = "", doc_name: str = ""
) -> dict[str, str]:
    """Read + mask locally. The returned dict is the ONLY thing that enters the graph."""
    text = raw_text
    if text is None and file_path is not None:
        path = Path(file_path)
        text = await asyncio.to_thread(_read_path, path)
        filename = filename or path.name
    if not isinstance(text, str) or not text.strip():
        raise ValueError(_EMPTY_TEXT_MSG)
    return {"text": mask_personal_data(text), "filename": resolve_doc_alias(filename, doc_name)}


async def analyze(graph: Any, *, config: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """``prepare_input`` + run the graph; returns the final state."""
    return await graph.ainvoke(await prepare_input(**kwargs), config)


async def analyze_stream(
    graph: Any, *, config: dict[str, Any] | None = None, stream_mode: str = "updates", **kwargs: Any
) -> AsyncIterator[Any]:
    async for chunk in graph.astream(await prepare_input(**kwargs), config, stream_mode=stream_mode):
        yield chunk


def build_analyze_minuta_graph(
    pool: asyncpg.Pool,
    settings: Settings | None = None,
    *,
    min_type_score: float = 0.8,
    triage_cutoff: float = 0.2,
    confirm_cutoff: float = 0.5,
    norm_cutoff: float = 0.3,
    max_clauses: int = 45,
    checkpointer: Any = None,
) -> Any:
    """Compila o grafo de analise de minuta (roteamento condicional pos-classificacao).

    Rules are NOT arguments: they are read from the domain tables at the start of each analysis.
    """
    cfg = settings or Settings()
    params = {
        "min_type_score": min_type_score,
        "triage_cutoff": triage_cutoff,
        "confirm_cutoff": confirm_cutoff,
        "norm_cutoff": norm_cutoff,
        "max_clauses": max_clauses,
    }
    limiters: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()

    def _limiter() -> asyncio.Semaphore:
        # Um semaforo por event loop (Semaphore nao atravessa loops), compartilhado por todo o grafo.
        loop = asyncio.get_running_loop()
        return limiters.setdefault(loop, asyncio.Semaphore(_CONCURRENCY))

    async def jev(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        async with _limiter():
            return await call_jev(state, questions, cfg)

    async def embed(text: str) -> EmbeddingResult:
        async with _limiter():
            return await embed_text(text, cfg)

    async def llm(system: str, user: str, model: str | None = None) -> tuple[str, int]:
        use = cfg.model_copy(update={"CHAT_MODEL": model}) if model else cfg
        async with _limiter():
            return await chat_completion(system, user, use, temperature=0.1, max_tokens=900)

    async def rec(state: AnalyzeMinutaState, steps: list[dict[str, Any]]) -> None:
        await append_trail(pool, uuid.UUID(state["analysis_id"]), _snapshot_of(state), steps)

    def guarded(fn: Any) -> Any:
        """On failure, mark the analysis failed (error TYPE only, never a message that may hold text)."""

        @wraps(fn)
        async def inner(state: AnalyzeMinutaState) -> dict[str, Any]:
            try:
                return await fn(state)
            except Exception as e:
                if state.get("analysis_id"):
                    await finish_analysis(
                        pool,
                        uuid.UUID(state["analysis_id"]),
                        status="failed",
                        minuta_type=state.get("tipo"),
                        report={"error": type(e).__name__, "step": fn.__name__},
                    )
                raise

        return inner

    async def iniciar(state: AnalyzeMinutaState) -> dict[str, Any]:
        text = state.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(_NO_MASKED_TEXT_MSG)
        snap = await load_rules_snapshot(pool)
        alias = state.get("filename", "")
        aid = await start_analysis(pool, snap, filename_alias=alias, masked_text=text, params=params)
        meta = {
            "hash": snap.hash,
            "matrix_version": snap.matrix_version,
            "prompt_version": snap.prompt_version,
            "history_id": snap.history_id,
        }
        await append_trail(
            pool,
            aid,
            snap,
            [
                {
                    "step": "iniciar",
                    "input_summary": {"filename_alias": alias, "masked_chars": len(text)},
                    "decision": {"rules_hash": snap.hash, "domain_history_id": snap.history_id, "params": params},
                }
            ],
        )
        return {"analysis_id": str(aid), "rules": snap.content, "rules_meta": meta}

    async def classificar(state: AnalyzeMinutaState) -> dict[str, Any]:
        types = state["rules"]["types"]
        crit = {slug: t["classifier"] for slug, t in types.items()}
        crit["nao_suportado"] = _UNSUPPORTED
        q = {"tipo": {"type": "choice", "instructions": "Qual e o tipo do documento em `inicio`?", "criteria": crit}}
        res = await jev({"inicio": state["text"][:4000]}, q)
        a = res["answers"]["tipo"]
        prob = a.get("probabilities")
        score = prob.get(a["choice"]) if isinstance(prob, dict) else None
        score = float(score if score is not None else a.get("confidence") or 0)
        ok = a["choice"] in types and score >= min_type_score
        await rec(
            state,
            [
                {
                    "step": "classificar",
                    "input_summary": {"candidate_types": sorted(types), "masked_chars": min(len(state["text"]), 4000)},
                    "decision": {"tipo": a["choice"], "suportado": ok},
                    "score": score,
                    "cutoff": min_type_score,
                }
            ],
        )
        return {"tipo": a["choice"], "score_tipo": score, "suportado": ok, "stats": {}}

    async def ficha(state: AnalyzeMinutaState) -> dict[str, Any]:
        t = re.sub(r"\s+", " ", state["text"])
        cands = extract_ficha_candidates(t)
        datas, prazos, valores = cands["datas"], cands["prazos"], cands["valores"]
        q = {
            "data_inicio": _choice_question("Qual e a data de inicio da vigencia da locacao em `contrato`?", datas, _NC),
            "prazo": _choice_question(
                "Qual e o prazo de duracao da locacao em `contrato`?",
                prazos,
                {**_NC, "indeterminado": "O contrato e por prazo indeterminado."},
            ),
            "valor_aluguel": _choice_question("Qual e o valor mensal do aluguel em `contrato`?", valores, _NC),
            "garantia": {
                "type": "choice",
                "instructions": "Qual garantia locaticia o `contrato` exige?",
                "criteria": {
                    "caucao": "Caucao em dinheiro ou bens.",
                    "fiador": "Fianca prestada por fiador.",
                    "seguro_fianca": "Seguro de fianca locaticia.",
                    "titulo": "Titulo de capitalizacao ou cessao de quotas.",
                    "sem_garantia": "Nao exige garantia.",
                    "multiplas": "Exige mais de uma modalidade.",
                },
            },
            "indice": {
                "type": "choice",
                "instructions": "Qual indice reajusta o aluguel em `contrato`?",
                "criteria": {
                    "igpm": "IGP-M.",
                    "ipca": "IPCA.",
                    "inpc": "INPC.",
                    "outro": "Outro indice.",
                    "nao_consta": "O contrato nao informa indice.",
                },
            },
        }
        r = await jev({"contrato": t}, q)
        ans = r["answers"]
        fc = {k: v.get("confidence") for k, v in ans.items()}
        fi = {
            "data_inicio": _pick(ans["data_inicio"], datas),
            "prazo": _pick(ans["prazo"], prazos),
            "valor_aluguel": _pick(ans["valor_aluguel"], valores),
            "garantia": ans["garantia"]["choice"],
            "indice": ans["indice"]["choice"],
        }
        await rec(
            state,
            [
                {
                    "step": "ficha",
                    "input_summary": {"candidates": {k: len(v) for k, v in cands.items()}},
                    "decision": {"ficha": fi, "confianca": fc},
                }
            ],
        )
        return {"ficha": fi, "ficha_confianca": fc, "stats": {**state.get("stats", {}), "jev_tokens_ficha": _tokens(r)}}

    async def triar(state: AnalyzeMinutaState) -> dict[str, Any]:
        T = _type_rules(state)
        riscos_m = T["riscos"]
        p_risco = _prompt(T, "triagem_risco")["text"]
        p_conf = _prompt(T, "confirmar_risco")["text"]
        textos = segment_clauses(state["text"])
        q = {
            "risco": {"type": "noul", "instructions": p_risco, "criteria": _Q_RISCO_CRITERIA},
            "tema": {
                "type": "choice",
                "instructions": "Qual o tema principal de `clausula`?",
                "criteria": {k: T["tema_desc"].get(k) or k.replace("_", " ") for k in T["temas"]},
            },
        }

        async def triagem(texto: str) -> tuple[float, str, int]:
            r = await jev({"clausula": texto}, q)
            return r["answers"]["risco"]["noul"], r["answers"]["tema"]["choice"], _tokens(r)

        res = await _gather([triagem(t) for t in textos])
        clausulas = [
            {"n": i + 1, "texto": textos[i], "risco": res[i][0], "tema": res[i][1], "triado": res[i][0] >= triage_cutoff}
            for i in range(len(textos))
        ]

        async def checar(cl: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
            lista = riscos_m.get(cl["tema"]) or []
            if not cl["triado"] or not lista:  # triagem abaixo do corte: sem checagem de riscos
                return [], 0
            qs = {
                x["id"]: {
                    "type": "noul",
                    "instructions": p_conf.replace("{risco}", x["risco"]),
                    "criteria": {
                        "true": "A clausula, combinada com a ficha, configura o risco descrito.",
                        "false": "O risco nao se configura nesta clausula.",
                    },
                }
                for x in lista
            }
            r = await jev({"clausula": cl["texto"], "ficha": state.get("ficha", {})}, qs)
            return [{**x, "noul": r["answers"][x["id"]]["noul"]} for x in lista], _tokens(r)

        feitos = await _gather([checar(cl) for cl in clausulas])
        extra = 0
        steps = []
        for cl, (checks, tk) in zip(clausulas, feitos, strict=True):
            cl["checks"] = [{"id": x["id"], "risco": x["risco"], "noul": x["noul"]} for x in checks]
            cl["confirmados"] = [x for x in checks if x["noul"] >= confirm_cutoff]
            passou_triagem = cl["triado"]
            cl["triado"] = bool(cl["confirmados"])
            extra += tk
            steps.append(
                {
                    "step": "triar",
                    "clause_n": cl["n"],
                    "input_summary": {"masked_chars": len(cl["texto"]), "excerpt": cl["texto"][:_EXCERPT]},
                    "decision": {
                        "tema": cl["tema"],
                        "passou_triagem": passou_triagem,
                        "checks": [{"id": c["id"], "noul": c["noul"]} for c in cl["checks"]],
                        "confirm_cutoff": confirm_cutoff,
                        "confirmados": [x["id"] for x in cl["confirmados"]],
                    },
                    "score": cl["risco"],
                    "cutoff": triage_cutoff,
                }
            )
        await rec(state, steps)
        triadas = sum(1 for c in clausulas if c["triado"])
        return {
            "clausulas": clausulas,
            "stats": {
                **state.get("stats", {}),
                "clausulas_total": len(clausulas),
                "clausulas_triadas": triadas,
                "jev_tokens": sum(x[2] for x in res) + extra,
            },
        }

    async def _norm_texts(names: list[str]) -> dict[str, str]:
        if not names:
            return {}
        rows = await pool.fetch(
            "SELECT d.title, string_agg(c.content, E'\\n' ORDER BY c.sequence_order) AS texto "
            "FROM kb_docs d JOIN kb_chunks c ON c.doc_id = d.id "
            "WHERE d.title = ANY($1::text[]) GROUP BY d.title",
            names,
        )
        return {r["title"]: r["texto"][:1200] for r in rows}

    async def buscar(state: AnalyzeMinutaState) -> dict[str, Any]:
        T = _type_rules(state)
        p_regula = _prompt(T, "regula_norma")["text"]
        q_regula = {"regula": {"type": "noul", "instructions": p_regula, "criteria": _Q_REGULA_CRITERIA}}
        # id da norma -> citacao, a partir da matriz de riscos: chave unica para lookup e dedup.
        id_to_citacao = {
            n["id"]: n["citacao"]
            for lista in T["riscos"].values()
            for x in lista
            for n in x.get("normas", [])
            if n.get("id") and n.get("citacao")
        }
        clausulas = state["clausulas"]
        refs = {
            n["citacao"]
            for cl in clausulas
            for x in cl.get("confirmados", [])
            for n in x.get("normas", [])
            if n.get("citacao")
        }
        tema_cit = {t: [id_to_citacao.get(i, i) for i in ids] for t, ids in T["tema_map"].items()}
        obrig = await _norm_texts(sorted(refs | {c for cs in tema_cit.values() for c in cs}))

        async def buscar_clausula(cl: dict[str, Any]) -> int:
            if not cl["triado"]:
                cl["normas"] = []
                return 0
            emb = await embed(cl["texto"])
            docs = await hybrid_search_rrf(pool, cl["texto"], emb.vector, emb.model, top_k=20)

            async def nota(d: dict[str, Any]) -> tuple[float, int]:
                r = await jev({"clausula": cl["texto"], "dispositivo": d["content"]}, q_regula)
                return r["answers"]["regula"]["noul"], _tokens(r)

            res = await _gather([nota(d) for d in docs])
            ordem = sorted(range(len(docs)), key=lambda i: -res[i][0])
            cl["candidatas"] = [{"citacao": docs[i]["title"], "nota": res[i][0]} for i in ordem[:8]]
            normas: list[dict[str, Any]] = []
            vistos: set[str] = set()
            for i in ordem:
                d = docs[i]
                if res[i][0] < norm_cutoff or d["title"] in vistos or len(normas) >= 3:
                    continue
                vistos.add(d["title"])
                normas.append({"citacao": d["title"], "texto": d["content"][:1200], "nota": res[i][0], "origem": "busca"})
            matriz = [n["citacao"] for x in cl["confirmados"] for n in x.get("normas", []) if n.get("citacao")]
            for c in matriz + tema_cit.get(cl["tema"], []):
                # Sem texto na base a norma nao entra: o redator so pode citar o que tem texto.
                if c not in vistos and obrig.get(c):
                    vistos.add(c)
                    normas.append({"citacao": c, "texto": obrig[c], "nota": None, "origem": "matriz"})
            cl["normas"] = normas
            return sum(x[1] for x in res)

        tokens = sum(await _gather([buscar_clausula(cl) for cl in clausulas]))
        steps = [
            {
                "step": "buscar",
                "clause_n": cl["n"],
                "input_summary": {"masked_chars": len(cl["texto"])},
                "decision": {
                    "normas": [
                        {"citacao": n["citacao"], "nota": n.get("nota"), "origem": n.get("origem")} for n in cl["normas"]
                    ],
                    "norm_cutoff": norm_cutoff,
                },
                "score": max((n["nota"] for n in cl["normas"] if n.get("nota") is not None), default=None),
                "cutoff": norm_cutoff,
                "cited_norms": [n["citacao"] for n in cl["normas"]],
            }
            for cl in clausulas
            if cl.get("triado")
        ]
        await rec(state, steps)
        stats = state.get("stats", {})
        return {"clausulas": clausulas, "stats": {**stats, "jev_tokens": stats.get("jev_tokens", 0) + tokens}}

    async def analisar(state: AnalyzeMinutaState) -> dict[str, Any]:
        T = _type_rules(state)
        redator = _prompt(T, "redigir_system")
        clausulas = state["clausulas"]
        fila = sorted(
            (c for c in clausulas if c.get("confirmados")),
            key=lambda c: -max(x["noul"] for x in c["confirmados"]),
        )
        redigir, fora = fila[:max_clauses], fila[max_clauses:]

        async def redigir_um(cl: dict[str, Any]) -> tuple[dict[str, Any], str, int]:
            riscos_txt = "\n".join(f"- {x['id']}: {x['risco']}" for x in cl["confirmados"])
            normas_txt = "\n".join(f"- {n['citacao']}: {n['texto']}" for n in cl["normas"]) or "(nenhuma)"
            msg = (
                "Ficha do contrato: " + json.dumps(state.get("ficha", {}), ensure_ascii=False)
                + "\nRiscos confirmados:\n" + riscos_txt
                + "\nNormas:\n" + normas_txt
                + "\n<clausula>" + cl["texto"] + "</clausula>"
            )
            bruto = ""
            try:
                bruto, used = await llm(redator["text"], msg, redator.get("model"))
                m = re.search(r"\{.*\}", bruto, re.S)
                if m is None:
                    raise ValueError("no json")
                return json.loads(m.group(0)), bruto, used
            except Exception as e:  # noqa: BLE001 - so o tipo, nunca a mensagem (pode conter texto)
                return {"erro": type(e).__name__}, bruto, 0

        res = await _gather([redigir_um(cl) for cl in redigir])
        for cl, (a, bruto, _) in zip(redigir, res, strict=True):
            cl["analise"] = a
            cl["analise_bruta"] = bruto
        stats = {
            **state.get("stats", {}),
            "tokens_analise": sum(x[2] for x in res),
            "nao_redigidas": len(fora),
            "falhas_redacao": sum(1 for a, _, _ in res if "erro" in a),
        }
        await rec(
            state,
            [
                {
                    "step": "analisar",
                    "input_summary": {"clausulas_com_risco": len(fila)},
                    "decision": {
                        "redigidas": len(redigir),
                        "nao_redigidas": len(fora),
                        "falhas": stats["falhas_redacao"],
                        "redator_model": redator.get("model"),
                    },
                }
            ],
        )
        return {"clausulas": clausulas, "stats": stats}

    async def validar(state: AnalyzeMinutaState) -> dict[str, Any]:
        report, env, diag = validate_and_format(dict(state))
        content = env.get("content", {})
        await rec(
            state,
            [
                {
                    "step": "validar",
                    "input_summary": {"clausulas": len(state.get("clausulas") or [])},
                    "decision": {
                        "status": env.get("status"),
                        "counts": content.get("counts"),
                        "alerts": [
                            {"risk_id": a["risk_id"], "severity": a["severity"], "clause_index": a["clause_index"]}
                            for a in content.get("alerts", [])
                        ],
                        "funil": diag.get("funil"),
                    },
                    "cited_norms": sorted({n for a in content.get("alerts", []) for n in a["legal_basis"]}),
                }
            ],
        )
        await finish_analysis(
            pool, uuid.UUID(state["analysis_id"]), status=env["status"], minuta_type=state.get("tipo"), report=env
        )
        return {"report_text": report, "report_envelope": env, "diagnostics": diag}

    builder = StateGraph(AnalyzeMinutaState)
    builder.add_node("iniciar", guarded(iniciar))
    builder.add_node("classificar", guarded(classificar))
    builder.add_node("ficha", guarded(ficha))
    builder.add_node("triar", guarded(triar))
    builder.add_node("buscar", guarded(buscar))
    builder.add_node("analisar", guarded(analisar))
    builder.add_node("validar", guarded(validar))
    builder.add_edge(START, "iniciar")
    builder.add_edge("iniciar", "classificar")
    builder.add_conditional_edges("classificar", route_after_classificar, {"ficha": "ficha", "validar": "validar"})
    builder.add_edge("ficha", "triar")
    builder.add_edge("triar", "buscar")
    builder.add_edge("buscar", "analisar")
    builder.add_edge("analisar", "validar")
    builder.add_edge("validar", END)
    return builder.compile(checkpointer=checkpointer)
