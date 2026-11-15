"""Tela de administracao: tipos de minuta, relatorios e prompts.

A configuracao e lida do banco a cada analise, entao salvar aqui vale na
proxima execucao. A tela nao tem autenticacao: mantenha o Streamlit em
localhost ou proteja o acesso por fora.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import asyncpg
import streamlit as st

from src.config import Settings
from src.db.config_admin import (
    VALID_KINDS,
    ConfigAdminError,
    create_minuta_type,
    create_report,
    delete_minuta_type,
    delete_report,
    rename_minuta_type,
    swap_report_order,
    update_report,
)
from src.db.config_repo import list_minuta_types, list_reports
from src.ui.runtime import ensure_schema, with_pool

KIND_LABELS = {"parecer": "Parecer (texto)", "checklist": "Checklist (tabela)"}
FLASH_KEY = "_admin_flash"


def _run(settings: Settings, work):
    """Executa uma operacao de banco e converte falhas conhecidas em st.error."""
    try:
        return asyncio.run(with_pool(settings, work))
    except ConfigAdminError as exc:
        st.error(str(exc))
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        st.error(
            f"Nao foi possivel acessar o banco ({type(exc).__name__}). "
            "Verifique a DATABASE_URL e se o Postgres esta no ar."
        )
    st.stop()


def _flash(message: str) -> None:
    """Guarda a confirmacao para o rerun seguinte."""
    st.session_state[FLASH_KEY] = message


def _type_section(settings: Settings, types) -> None:
    st.subheader("Tipos de minuta")
    selected = (
        st.selectbox("Tipo", options=types, format_func=lambda t: t.name, key="admin_type")
        if types
        else None
    )
    if selected is None:
        st.info("Nenhum tipo cadastrado. Crie o primeiro abaixo.")

    if selected is not None:
        with st.form(f"rename_{selected.id}"):
            new_name = st.text_input("Nome do tipo", value=selected.name)
            rename = st.form_submit_button("Renomear")
        if rename:
            _run(settings, lambda p: rename_minuta_type(p, selected.id, new_name))
            _flash("Tipo renomeado.")
            st.rerun()

        with st.form(f"delete_{selected.id}"):
            confirm = st.checkbox("Confirmo excluir este tipo")
            delete = st.form_submit_button("Excluir tipo")
        if delete:
            if not confirm:
                st.error("Marque a confirmacao para excluir o tipo.")
            else:
                _run(settings, lambda p: delete_minuta_type(p, selected.id))
                _flash("Tipo excluido.")
                st.rerun()

    with st.form("create_type", clear_on_submit=True):
        name = st.text_input("Nome do novo tipo")
        create = st.form_submit_button("Criar tipo")
    if create:
        _run(settings, lambda p: create_minuta_type(p, name))
        _flash("Tipo criado.")
        st.rerun()


def _reports_section(settings: Settings, type_) -> None:
    reports = _run(settings, lambda p: list_reports(p, type_.id))
    st.subheader(f"Relatorios de {type_.name}")

    if not reports:
        st.info("Nenhum relatorio cadastrado. Crie o primeiro abaixo.")

    for index, report in enumerate(reports):
        with st.expander(f"{report.execution_order}. {report.name}"):
            with st.form(f"report_{report.id}"):
                name = st.text_input("Nome", value=report.name)
                kind = st.selectbox(
                    "Saida",
                    options=list(VALID_KINDS),
                    index=list(VALID_KINDS).index(report.kind),
                    format_func=KIND_LABELS.get,
                )
                model = st.text_input(
                    "Modelo (vazio usa o CHAT_MODEL)", value=report.model or ""
                )
                prompt = st.text_area("Prompt", value=report.prompt, height=240)
                save = st.form_submit_button("Salvar")
                confirm = st.checkbox("Confirmo excluir este relatorio")
                delete = st.form_submit_button("Excluir relatorio")

            if save:
                _run(
                    settings,
                    lambda p, r=report: update_report(
                        p,
                        type_.id,
                        r.id,
                        name=name,
                        kind=kind,
                        prompt=prompt,
                        model=model,
                    ),
                )
                _flash(f"Relatorio {name.strip()!r} salvo.")
                st.rerun()

            if delete:
                if not confirm:
                    st.error("Marque a confirmacao para excluir o relatorio.")
                else:
                    _run(
                        settings,
                        lambda p, r=report: delete_report(p, type_.id, r.id),
                    )
                    _flash("Relatorio excluido.")
                    st.rerun()

            columns = st.columns(2)
            if index > 0 and columns[0].button("Subir", key=f"up_{report.id}"):
                _run(
                    settings,
                    lambda p: swap_report_order(
                        p, type_.id, reports[index - 1].id, report.id
                    ),
                )
                _flash("Ordem atualizada.")
                st.rerun()
            if index < len(reports) - 1 and columns[1].button(
                "Descer", key=f"down_{report.id}"
            ):
                _run(
                    settings,
                    lambda p: swap_report_order(
                        p, type_.id, report.id, reports[index + 1].id
                    ),
                )
                _flash("Ordem atualizada.")
                st.rerun()

    with st.form("create_report", clear_on_submit=True):
        st.markdown("**Novo relatorio**")
        new_name = st.text_input("Nome")
        new_kind = st.selectbox(
            "Saida", options=list(VALID_KINDS), format_func=KIND_LABELS.get
        )
        new_model = st.text_input("Modelo (opcional)")
        new_prompt = st.text_area("Prompt", height=200)
        create = st.form_submit_button("Criar relatorio")
    if create:
        _run(
            settings,
            lambda p: create_report(
                p,
                type_.id,
                name=new_name,
                kind=new_kind,
                prompt=new_prompt,
                model=new_model,
            ),
        )
        _flash("Relatorio criado.")
        st.rerun()


def main() -> None:
    st.title("Administracao")
    st.caption(
        "A configuracao e lida do banco a cada analise: salvar aqui vale na proxima "
        "execucao. Novos tipos de saida e hooks ainda exigem codigo."
    )

    settings = Settings()
    try:
        ensure_schema(settings.DATABASE_URL)
        types = asyncio.run(with_pool(settings, list_minuta_types))
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        st.error(
            f"Nao foi possivel acessar o banco ({type(exc).__name__}). "
            "Verifique a DATABASE_URL e se o Postgres esta no ar."
        )
        st.stop()

    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)

    _type_section(settings, types)
    st.divider()

    if types:
        selected = st.session_state.get("admin_type", types[0])
        _reports_section(settings, selected)
    else:
        st.info("Crie um tipo de minuta para cadastrar relatorios.")


main()
