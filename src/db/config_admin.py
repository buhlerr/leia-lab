"""Escrita da configuracao de minutas: tipos e relatorios.

Usado pela tela de administracao. As constraints de ``schema_config.sql``
continuam sendo a ultima linha de defesa; aqui elas viram mensagens claras e
operacoes transacionais (troca de ordem, exclusao protegida).
"""

from __future__ import annotations

import asyncpg

VALID_KINDS = ("parecer", "checklist")
# A ordem de execucao e unica por tipo; o deslocamento libera as duas posicoes
# antes de gravar a troca, sem violar a constraint no meio da transacao.
ORDER_OFFSET = 1_000_000


class ConfigAdminError(Exception):
    """Falha de validacao ou de constraint ao gravar a configuracao."""


def validate_type_name(name: str) -> str:
    """Nome de tipo aparado e nao vazio."""
    cleaned = name.strip()
    if not cleaned:
        raise ConfigAdminError("O nome do tipo nao pode ficar vazio.")
    return cleaned


def validate_report(
    name: str, kind: str, prompt: str, model: str | None
) -> tuple[str, str, str, str | None]:
    """Campos de um relatorio aparados e validados antes de ir ao banco."""
    cleaned_name = name.strip()
    cleaned_prompt = prompt.strip()
    cleaned_model = (model or "").strip() or None
    if not cleaned_name:
        raise ConfigAdminError("O nome do relatorio nao pode ficar vazio.")
    if kind not in VALID_KINDS:
        raise ConfigAdminError(f"Tipo de saida invalido: {kind!r}.")
    if not cleaned_prompt:
        raise ConfigAdminError("O prompt do relatorio nao pode ficar vazio.")
    return cleaned_name, kind, cleaned_prompt, cleaned_model


async def create_minuta_type(pool: asyncpg.Pool, name: str) -> str:
    """Cria um tipo e devolve o id."""
    cleaned = validate_type_name(name)
    try:
        return str(
            await pool.fetchval(
                "INSERT INTO minuta_types (name) VALUES ($1) RETURNING id", cleaned
            )
        )
    except asyncpg.UniqueViolationError as exc:
        raise ConfigAdminError(f"Ja existe um tipo chamado {cleaned!r}.") from exc


async def rename_minuta_type(
    pool: asyncpg.Pool, minuta_type_id: str, name: str
) -> None:
    """Renomeia um tipo, recusando nome vazio ou ja usado por outro tipo."""
    cleaned = validate_type_name(name)
    try:
        status = await pool.execute(
            "UPDATE minuta_types SET name = $1 WHERE id = $2::uuid",
            cleaned,
            minuta_type_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise ConfigAdminError(f"Ja existe um tipo chamado {cleaned!r}.") from exc
    if status == "UPDATE 0":
        raise ConfigAdminError("Tipo de minuta nao encontrado.")


async def delete_minuta_type(pool: asyncpg.Pool, minuta_type_id: str) -> None:
    """Exclui um tipo sem relatorios; a FK RESTRICT protege os demais."""
    try:
        status = await pool.execute(
            "DELETE FROM minuta_types WHERE id = $1::uuid", minuta_type_id
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise ConfigAdminError(
            "Exclua os relatorios deste tipo antes de remove-lo."
        ) from exc
    if status == "DELETE 0":
        raise ConfigAdminError("Tipo de minuta nao encontrado.")


async def create_report(
    pool: asyncpg.Pool,
    minuta_type_id: str,
    *,
    name: str,
    kind: str,
    prompt: str,
    model: str | None,
) -> str:
    """Acrescenta um relatorio ao fim da ordem de execucao do tipo."""
    cleaned_name, kind, cleaned_prompt, cleaned_model = validate_report(
        name, kind, prompt, model
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists = await conn.fetchval(
                "SELECT 1 FROM minuta_types WHERE id = $1::uuid", minuta_type_id
            )
            if not exists:
                raise ConfigAdminError("Tipo de minuta nao encontrado.")
            next_order = await conn.fetchval(
                """
                SELECT COALESCE(MAX(execution_order), 0) + 1
                FROM minuta_reports
                WHERE minuta_type_id = $1::uuid
                """,
                minuta_type_id,
            )
            try:
                return str(
                    await conn.fetchval(
                        """
                        INSERT INTO minuta_reports
                            (minuta_type_id, name, kind, prompt, model, execution_order)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6)
                        RETURNING id
                        """,
                        minuta_type_id,
                        cleaned_name,
                        kind,
                        cleaned_prompt,
                        cleaned_model,
                        next_order,
                    )
                )
            except asyncpg.UniqueViolationError as exc:
                raise ConfigAdminError(
                    "Ja existe um relatorio com esse nome neste tipo."
                ) from exc


async def update_report(
    pool: asyncpg.Pool,
    minuta_type_id: str,
    report_id: str,
    *,
    name: str,
    kind: str,
    prompt: str,
    model: str | None,
) -> None:
    """Atualiza nome, saida, prompt e modelo de um relatorio existente."""
    cleaned_name, kind, cleaned_prompt, cleaned_model = validate_report(
        name, kind, prompt, model
    )
    try:
        status = await pool.execute(
            """
            UPDATE minuta_reports
            SET name = $1, kind = $2, prompt = $3, model = $4
            WHERE id = $5::uuid AND minuta_type_id = $6::uuid
            """,
            cleaned_name,
            kind,
            cleaned_prompt,
            cleaned_model,
            report_id,
            minuta_type_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise ConfigAdminError(
            "Ja existe um relatorio com esse nome neste tipo."
        ) from exc
    if status == "UPDATE 0":
        raise ConfigAdminError("Relatorio nao encontrado neste tipo.")


async def delete_report(
    pool: asyncpg.Pool, minuta_type_id: str, report_id: str
) -> None:
    """Exclui um relatorio do tipo informado."""
    status = await pool.execute(
        "DELETE FROM minuta_reports WHERE id = $1::uuid AND minuta_type_id = $2::uuid",
        report_id,
        minuta_type_id,
    )
    if status == "DELETE 0":
        raise ConfigAdminError("Relatorio nao encontrado neste tipo.")


async def swap_report_order(
    pool: asyncpg.Pool,
    minuta_type_id: str,
    first_id: str,
    second_id: str,
) -> None:
    """Troca a posicao de dois relatorios do mesmo tipo."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id::text AS id, execution_order
                FROM minuta_reports
                WHERE id = ANY($1::uuid[]) AND minuta_type_id = $2::uuid
                FOR UPDATE
                """,
                [first_id, second_id],
                minuta_type_id,
            )
            if len(rows) != 2:
                raise ConfigAdminError("Relatorios nao encontrados neste tipo.")
            orders = {row["id"]: row["execution_order"] for row in rows}
            first_order = orders[first_id]
            second_order = orders[second_id]

            await conn.execute(
                """
                UPDATE minuta_reports
                SET execution_order = execution_order + $1
                WHERE id = ANY($2::uuid[]) AND minuta_type_id = $3::uuid
                """,
                ORDER_OFFSET,
                [first_id, second_id],
                minuta_type_id,
            )
            await conn.execute(
                "UPDATE minuta_reports SET execution_order = $1 WHERE id = $2::uuid",
                second_order,
                first_id,
            )
            await conn.execute(
                "UPDATE minuta_reports SET execution_order = $1 WHERE id = $2::uuid",
                first_order,
                second_id,
            )
