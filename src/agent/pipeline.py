"""Pipeline de relatorios: roda os relatorios de um tipo de minuta em sequencia."""

from __future__ import annotations

import logging

import asyncpg
import httpx
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.usage import RunUsage

from src.agent.classifier import classify_minuta
from src.agent.llm import build_model, minuta_system_prompt
from src.agent.outputs import AnalysisResult, ChecklistItem, ChecklistOutput, ReportResult
from src.agent.tools import AnalysisDeps, search_kb
from src.config import Settings
from src.db.config_repo import (
    MinutaReport,
    get_minuta_type,
    list_minuta_types,
    list_reports,
)

logger = logging.getLogger(__name__)

MAX_MINUTA_CHARS = 200_000
ERROR_TEXT_LIMIT = 300
REPORT_REQUEST = "Execute o relatorio pedido nas instrucoes."
# TestModel nao gera saida em JSON sozinho; o modo offline precisa de uma pronta.
OFFLINE_CHECKLIST_JSON = ChecklistOutput(
    items=[ChecklistItem(item="[modo offline]", status="ausente", evidence="Resultado simulado.")]
).model_dump_json()


class AnalysisError(Exception):
    """Falha que impede a analise da minuta."""


class MinutaTooLargeError(AnalysisError):
    """O texto da minuta passa do limite aceito."""


class EmptyMinutaError(AnalysisError):
    """O texto da minuta esta vazio."""


class MinutaTypeNotIdentifiedError(AnalysisError):
    """Nenhum tipo de minuta atende ao documento."""


class UnknownMinutaTypeError(AnalysisError):
    """O tipo de minuta informado nao existe."""


async def run_analysis(
    pool: asyncpg.Pool,
    text: str,
    settings: Settings,
    minuta_type_id: str | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> AnalysisResult:
    """Analisa a minuta com os relatorios do seu tipo, em ordem de execucao."""
    if not text.strip():
        raise EmptyMinutaError("A minuta esta vazia.")

    # Nunca trunque: um texto acima do limite e recusado por inteiro.
    if len(text) > MAX_MINUTA_CHARS:
        raise MinutaTooLargeError(
            f"A minuta tem {len(text)} caracteres; o limite e {MAX_MINUTA_CHARS}."
        )

    if minuta_type_id is not None:
        minuta_type = await get_minuta_type(pool, minuta_type_id)
        if minuta_type is None:
            raise UnknownMinutaTypeError(
                f"Tipo de minuta nao encontrado: {minuta_type_id}."
            )
    else:
        types = await list_minuta_types(pool)
        minuta_type = await classify_minuta(
            text, types, settings, http_client=http_client
        )
        if minuta_type is None:
            raise MinutaTypeNotIdentifiedError(
                "Nao foi possivel identificar o tipo da minuta."
            )

    # Sem cache: um UPDATE no prompt vale ja na execucao seguinte.
    reports = await list_reports(pool, minuta_type.id)
    deps = AnalysisDeps(pool=pool, settings=settings)

    results: list[ReportResult] = []
    for report in reports:
        # Uma falha em um relatorio nao interrompe os seguintes.
        results.append(await _run_report(report, text, deps, settings, http_client))

    return AnalysisResult(
        minuta_type_id=minuta_type.id,
        minuta_type_name=minuta_type.name,
        reports=results,
    )


async def _run_report(
    report: MinutaReport,
    text: str,
    deps: AnalysisDeps,
    settings: Settings,
    http_client: httpx.AsyncClient | None,
) -> ReportResult:
    """Um relatorio isolado: o erro fica registrado no proprio resultado."""
    is_checklist = report.kind == "checklist"
    # Checklist em JSON, nao por ferramenta de saida: a lista de ferramentas fica
    # igual em todos os relatorios e nao arrisca quebrar o prefixo do cache.
    output_type = PromptedOutput(ChecklistOutput) if is_checklist else str
    offline_text = (
        OFFLINE_CHECKLIST_JSON
        if is_checklist
        else f"[modo offline] Resultado simulado de {report.name}."
    )

    try:
        # A minuta fica no system_prompt, que vai antes das instructions: o
        # prefixo e identico entre relatorios e so o prompt de cada um varia.
        agent = Agent(
            build_model(
                settings,
                report.model,
                offline_text=offline_text,
                http_client=http_client,
            ),
            output_type=output_type,
            deps_type=AnalysisDeps,
            tools=[search_kb],
            system_prompt=minuta_system_prompt(text),
            instructions=report.prompt,
        )
        result = await agent.run(REPORT_REQUEST, deps=deps)
    except Exception as exc:
        # Nunca registre o texto da minuta: ele e confidencial.
        logger.warning(
            "Falha no relatorio %s: %s", report.name, type(exc).__name__
        )
        return ReportResult(
            name=report.name,
            kind=report.kind,
            execution_order=report.execution_order,
            status="failed",
            model=report.model or settings.CHAT_MODEL,
            error=f"{type(exc).__name__}: {str(exc)[:ERROR_TEXT_LIMIT]}",
        )

    return ReportResult(
        name=report.name,
        kind=report.kind,
        execution_order=report.execution_order,
        status="ok",
        text=None if is_checklist else result.output,
        checklist=result.output if is_checklist else None,
        model=report.model or settings.CHAT_MODEL,
        input_tokens=result.usage.input_tokens,
        cache_read_tokens=_cache_read_tokens(result.usage),
    )


def _cache_read_tokens(usage: RunUsage) -> int:
    """Tokens servidos do cache; a DeepSeek os informa em campo proprio."""
    return usage.cache_read_tokens or usage.details.get("prompt_cache_hit_tokens", 0)
