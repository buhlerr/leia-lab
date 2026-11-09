"""Tela Streamlit para analise de minutas contratuais."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

# O Streamlit executa este arquivo como script. Para que os imports do pacote
# `src` resolvam, insere a raiz do projeto (dois niveis acima de app.py) no
# sys.path antes de importar qualquer modulo do projeto.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg
import streamlit as st

from src.agent.outputs import AnalysisResult, ChecklistOutput, ReportResult
from src.agent.pipeline import (
    AnalysisError,
    MinutaTypeNotIdentifiedError,
    run_analysis,
)
from src.config import Settings
from src.db.config_repo import list_minuta_types
from src.db.connection import init_db
from src.ingest.extract import DocumentError, extract_text

# A saida do modelo e texto de terceiros. Imagem remota e o vetor de exfiltracao:
# o navegador busca a URL sozinho ao renderizar. Link comum so sai no clique.
HTML_MEDIA = re.compile(
    r"<\s*(img|iframe|object|embed|video|audio|source)\b[^>]*>", re.IGNORECASE
)
IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
LINK_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
ANGLE_AUTOLINK = re.compile(r"<(?=[a-z][a-z0-9+.\-]{1,31}:)", re.IGNORECASE)
# Sem `\b`: o GFM liga URLs logo depois de `_` ou digito.
BARE_URL = re.compile(r"(https?(?=://)|www(?=\.))", re.IGNORECASE)


def safe_markdown(text: str) -> str:
    """Mantem a formatacao do relatorio e tira o que o navegador carregaria sozinho."""
    text = HTML_MEDIA.sub("", text)
    # As definicoes vem antes das imagens: `![a][1]` perde o destino junto.
    text = LINK_DEFINITION.sub("", text)
    text = IMAGE.sub(r"\1", text)
    text = LINK.sub(r"\1", text)
    # As regex nao cobrem colchete aninhado nem definicao dentro de citacao ou lista.
    # Escapar estes tokens impede o parser de formar imagem ou link com o que sobrou.
    text = text.replace("![", "!\\[").replace("](", "]\\(").replace("]:", "]\\:")
    # Entidade em vez de barra: uma barra vinda do texto anularia a barra inserida.
    text = ANGLE_AUTOLINK.sub("&lt;", text)
    # Barra invertida nao basta: o GFM procura URLs no texto ja sem os escapes.
    return BARE_URL.sub("\\1\u200b", text)


def can_submit(has_api_key: bool, consent: bool) -> bool:
    """Permite envio quando nao ha chave (modo offline) ou quando ha consentimento."""
    return (not has_api_key) or consent


def retention_warning(provider: str, embedding_zero_retention: bool) -> str:
    """Aviso sobre o destino do texto, fiel a configuracao de retencao em vigor."""
    if provider == "deepseek":
        return (
            "O texto da minuta sera enviado a API da DeepSeek, com armazenamento na China "
            "e sem opcao de retencao zero: envie apenas minutas ficticias."
        )
    base = (
        "O texto da minuta sera enviado ao OpenRouter, com o chat restrito a endpoints "
        "sem retencao de dados. Mesmo assim, o texto sai desta maquina."
    )
    if embedding_zero_retention:
        return base + " As buscas na base de conhecimento seguem a mesma restricao."
    return (
        base + " As buscas na base de conhecimento, que podem conter trechos da minuta, "
        "usam um modelo gratuito SEM essa restricao: envie apenas minutas ficticias."
    )


def checklist_rows(checklist: ChecklistOutput) -> list[dict[str, str]]:
    """Converte um checklist em linhas para exibicao tabular."""
    return [
        {
            "Item": item.item,
            "Status": item.status,
            "Evidencia": item.evidence,
        }
        for item in checklist.items
    ]


def _render_report(report: ReportResult) -> None:
    """Renderiza um relatorio dentro de um container."""
    with st.container(border=True):
        header = st.columns([0.75, 0.25])
        with header[0]:
            st.markdown(f"**{report.name}**")
        with header[1]:
            if report.status == "ok":
                st.badge("ok", color="green")
            else:
                st.badge("falhou", color="red")

        if report.status == "ok":
            if report.text is not None:
                st.markdown(safe_markdown(report.text))
            if report.checklist is not None:
                st.dataframe(
                    checklist_rows(report.checklist),
                    hide_index=True,
                    width="stretch",
                )
        else:
            st.error(report.error or "Erro desconhecido no relatorio.")

        cache = (
            f" | Cache: {report.cache_read_tokens} de {report.input_tokens} tokens"
            if report.input_tokens
            else ""
        )
        st.caption(f"Modelo: {report.model}{cache}")


def _render_result(result: AnalysisResult) -> None:
    """Exibe o resultado completo da analise."""
    st.subheader(result.minuta_type_name)

    ok_count = sum(1 for r in result.reports if r.status == "ok")
    failed_count = len(result.reports) - ok_count
    st.caption(f"Relatorios: {ok_count} ok, {failed_count} falha(s)")

    for report in result.reports:
        _render_report(report)


async def _apply_schema(settings) -> None:
    """Aplica o schema em um pool proprio, fechado em seguida."""
    async with asyncpg.create_pool(
        dsn=settings.DATABASE_URL, min_size=1, max_size=2
    ) as pool:
        await init_db(pool)


@st.cache_resource(show_spinner=False)
def _ensure_schema(dsn: str) -> bool:
    """Aplica o schema uma vez por processo; falhas nao ficam no cache."""
    asyncio.run(_apply_schema(Settings(DATABASE_URL=dsn)))
    return True


async def _with_pool(settings, work):
    async with asyncpg.create_pool(
        dsn=settings.DATABASE_URL, min_size=1, max_size=4
    ) as pool:
        return await work(pool)


def main() -> None:
    st.title("Analise de minutas")

    settings = Settings()
    has_key = bool(settings.chat_api_key)

    if not has_key:
        st.info(
            "Voce esta em modo offline. Os resultados serao simulados e o texto da "
            "minuta nao e enviado a nenhum provedor.",
            icon="ℹ️",
        )
    else:
        st.warning(
            retention_warning(settings.CHAT_PROVIDER, settings.EMBEDDING_ZERO_RETENTION),
            icon="⚠️",
        )

    uploaded_file = st.file_uploader("Minuta (PDF ou DOCX)", type=["pdf", "docx"])

    # A confirmacao vale para um arquivo: trocar de minuta exige confirmar de novo.
    consent_key = f"consent_{uploaded_file.file_id}" if uploaded_file else "consent_none"
    if has_key:
        st.checkbox(
            "Confirmo o envio do texto desta minuta ao provedor externo",
            key=consent_key,
            disabled=uploaded_file is None,
        )

    try:
        _ensure_schema(settings.DATABASE_URL)
        types = asyncio.run(
            _with_pool(settings, lambda pool: list_minuta_types(pool))
        )
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        st.error(
            f"Nao foi possivel acessar o banco ({type(exc).__name__}). "
            "Verifique a DATABASE_URL e se o Postgres esta no ar."
        )
        st.stop()

    if not types:
        st.warning(
            "Nenhum tipo de minuta encontrado. Execute "
            "`uv run python -m scripts.seed_demo` para popular a configuracao."
        )
        st.stop()

    auto_option = "Identificar automaticamente"
    labels = [auto_option] + [t.name for t in types]
    selected_label = st.selectbox("Tipo da minuta", options=labels)
    type_id = None if selected_label == auto_option else next(t.id for t in types if t.name == selected_label)

    consent = st.session_state.get(consent_key, False)
    can_analyze = can_submit(has_key, consent)
    has_file = uploaded_file is not None

    if st.button("Analisar", type="primary", disabled=not (has_file and can_analyze)):
        if not can_analyze:
            st.error("Nao e possivel analisar sem consentimento.")
            st.stop()
        if not has_file:
            st.error("Selecione uma minuta antes de analisar.")
            st.stop()

        with st.spinner("Analisando a minuta..."):
            try:
                text = extract_text(uploaded_file.name, uploaded_file.getvalue())
                result = asyncio.run(
                    _with_pool(
                        settings,
                        lambda pool: run_analysis(pool, text, settings, type_id),
                    )
                )
            except DocumentError as exc:
                st.error(f"Erro ao ler o documento: {exc}")
                st.stop()
            except MinutaTypeNotIdentifiedError:
                st.error(
                    "Nao foi possivel identificar o tipo da minuta. "
                    "Escolha o tipo manualmente no seletor e clique em Analisar novamente."
                )
                st.stop()
            except AnalysisError as exc:
                st.error(f"Erro na analise: {exc}")
                st.stop()

        st.session_state["result"] = result

    if "result" in st.session_state:
        _render_result(st.session_state["result"])


if __name__ == "__main__":
    main()
