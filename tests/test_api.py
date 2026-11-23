"""Testes da API (``src/api``): contrato de resposta, auth de servico e privacidade.

Todo teste roda contra o banco de teste com as chaves pagas vazias (stubs
offline de Jev/LLM/embeddings), sem tocar o banco de desenvolvimento.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from contextlib import asynccontextmanager
from typing import Iterator

import docx
import httpx
import pytest

from src.api.app import ClientDisconnected, create_app, run_disconnect_guarded
from src.config import Settings
from src.db.connection import init_db
from src.graphs.ingest_graph import build_ingest_graph
from src.graphs.ingest_graph import ingest as run_ingest
from src.ingest.extract import MAX_UPLOAD_BYTES
from tests._capture import capture  # noqa: F401 - fixture
from tests._db_guard import SuiteSettings
from tests._rules_helper import use_rules

TEST_DATABASE_URL = SuiteSettings().TEST_DATABASE_URL
TOKEN = "token-de-servico-teste-8z6"

_RISCOS = {
    "reajuste_e_indexacao": [
        {
            "id": "REAJ-01",
            "risco": "Reajuste em periodicidade inferior a 12 meses",
            "cor": "vermelho",
            "parte": "locatario",
            "normas": [{"id": "lei-10192-2001-art-2", "citacao": "Lei 10.192/2001, art. 2º"}],
        }
    ]
}

# Nome real de arquivo e CPF de mentira: nada disso pode vazar em resposta, log ou linha.
_MINUTA = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    "LOCADOR: Carlos Eduardo Mendes, brasileiro, CPF 999.888.777-66.\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00.\n"
    "Cláusula 2ª - Do Reajuste: O aluguel será reajustado semestralmente pelo índice IGP-M."
)


@pytest.fixture
def api_settings() -> Settings:
    """Settings da API: banco de teste, modo offline, token de servico conhecido."""
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        OPENROUTER_API_KEY="",
        TYPESAFE_API_KEY="",
        LEIA_API_TOKEN=TOKEN,
        MLFLOW_TRACKING_URI="",  # nunca herdar o MLflow real do ambiente de quem roda a suite
    )


def _auth(idempotency_key: str | None = None) -> dict[str, str]:
    """Bearer de servico + ``Idempotency-Key`` (uma chave nova por chamada, salvo se dada)."""
    return {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": idempotency_key or str(uuid.uuid4())}


@asynccontextmanager
async def api_client(settings: Settings) -> Iterator[httpx.AsyncClient]:
    """App real (lifespan completo: pool + grafo) sem abrir socket."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def _docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_app_refuses_to_start_without_token() -> None:
    # Fail closed: sem token de servico o app nao sobe.
    with pytest.raises(RuntimeError):
        create_app(Settings(DATABASE_URL=TEST_DATABASE_URL, LEIA_API_TOKEN=""))


async def test_endpoints_require_bearer_token(pool, api_settings) -> None:
    async with api_client(api_settings) as client:
        assert (await client.get("/healthz")).status_code == 200
        for headers in ({}, {"Authorization": f"Bearer {TOKEN}-errada"}, {"Authorization": "Basic abc"}):
            r = await client.post(
                "/v1/analyses",
                files={"file": ("a.txt", b"CONTRATO DE LOCACAO", "text/plain")},
                headers=headers,
            )
            assert r.status_code == 401
            assert r.json()["code"] == "unauthorized"
        r = await client.get(f"/v1/analyses/{uuid.uuid4()}", headers={})
        assert r.status_code == 401


async def test_post_txt_returns_201_and_get_returns_the_same_contract(pool, api_settings) -> None:
    await init_db(pool)
    ingest = build_ingest_graph(pool, api_settings)
    await run_ingest(
        ingest,
        **{
            "raw_text": "Lei 10.192/2001, art. 2º - É nula de pleno direito a estipulação de reajuste em periodicidade inferior a um ano.",
            "filename": "lei-10192-2001-art-2.txt",
            "doc_name": "Lei 10.192/2001, art. 2º",
        },
    )
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])

    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("Joao-da-Silva-contrato.txt", _MINUTA.encode("utf-8"), "text/plain")},
            headers=_auth(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "done"
        assert body["minuta_type"] == "locacao_residencial"
        assert body["filename_alias"].startswith("documento-") and body["filename_alias"].endswith(".txt")
        assert body["matrix_version"] and body["prompt_version"] and body["rules_hash"]
        # Contrato exato, derivado da minuta e das regras semeadas: duas clausulas,
        # ambas confirmam REAJ-01 (vermelho) com o fundamento da matriz.
        alerts = body["report"]["content"]["alerts"]
        assert [(a["risk_id"], a["severity"], a["clause_index"]) for a in alerts] == [
            ("REAJ-01", "red", 1),
            ("REAJ-01", "red", 2),
        ]
        assert alerts[0]["legal_basis"] == ["Lei 10.192/2001, art. 2º"]
        # Contrato da trilha: ordenada, comeca em iniciar, termina em validar, e cada
        # clausula tem seus passos triar e buscar. Passos intermediarios do grafo nao
        # sao contrato da API: um passo novo nao pode quebrar este teste.
        steps = [(s["step"], s["clause_n"]) for s in body["trail"]]
        assert steps[0] == ("iniciar", None)
        assert steps[-1] == ("validar", None)
        assert [n for s, n in steps if s == "triar"] == [1, 2]
        assert [n for s, n in steps if s == "buscar"] == [1, 2]
        aid = uuid.UUID(body["analysis_id"])  # contrato: e um UUID valido

        got = await client.get(f"/v1/analyses/{body['analysis_id']}", headers=_auth())
        assert got.status_code == 200
        assert got.json() == body  # GET devolve exatamente o mesmo contrato

    # Privacidade: nome real do arquivo e CPF nunca aparecem na resposta.
    assert "Joao-da-Silva" not in r.text
    assert "999.888.777-66" not in r.text

    row = await pool.fetchrow(
        "SELECT filename_alias, text_sha256, rules_snapshot::text AS snapshot, report::text AS report "
        "FROM analyses WHERE id = $1::uuid",
        aid,
    )
    row_text = " ".join(str(v) for v in row.values())
    assert "Joao-da-Silva" not in row_text
    assert "999.888.777-66" not in row_text

    trail = await pool.fetchval(
        "SELECT string_agg(t::text, ' ') FROM analysis_trail t WHERE t.analysis_id = $1::uuid", aid
    )
    assert "Joao-da-Silva" not in (trail or "")
    assert "999.888.777-66" not in (trail or "")


async def test_post_docx_returns_201_with_trail(pool, api_settings) -> None:
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])

    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("Contrato-do-Fiador-Vanderlei.docx", _docx_bytes(_MINUTA), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=_auth(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "done"
        # Mesmo contrato exato da outra via de upload: REAJ-01 em cada clausula e a
        # trilha ordenada nos extremos, com cada clausula coberta (sem pinar os
        # passos intermediarios do grafo).
        assert [(a["risk_id"], a["severity"], a["clause_index"]) for a in body["report"]["content"]["alerts"]] == [
            ("REAJ-01", "red", 1),
            ("REAJ-01", "red", 2),
        ]
        steps = [(s["step"], s["clause_n"]) for s in body["trail"]]
        assert steps[0] == ("iniciar", None)
        assert steps[-1] == ("validar", None)
        assert [n for s, n in steps if s == "triar"] == [1, 2]
        assert [n for s, n in steps if s == "buscar"] == [1, 2]
        assert body["filename_alias"].startswith("documento-") and body["filename_alias"].endswith(".docx")
        assert "Vanderlei" not in r.text


async def test_post_exe_returns_415(pool, api_settings) -> None:
    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("Malware-do-Joao.exe", b"MZ\x90\x00\x03\x00", "application/octet-stream")},
            headers=_auth(),
        )
        assert r.status_code == 415
        assert r.json()["code"] == "unsupported_file"
        assert "Joao" not in r.text  # mensagem generica: sem eco do nome real


async def test_post_docx_lento_returns_422_document_timeout(pool, api_settings, monkeypatch) -> None:
    """O timeout de leitura chega ao cliente com o contrato proprio (422/document_timeout),
    nao o de arquivo grande demais -- a confusao que o leia-lab-cxe.5 corrigiu."""
    from src.ingest.extract import DocumentTimeoutError

    def lento(extension: str, data: bytes, **kwargs: object) -> str:
        raise DocumentTimeoutError("leitura lenta")

    monkeypatch.setattr("src.api.service.extract_text_isolated", lento)
    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("Contrato.docx", _docx_bytes(_MINUTA), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            headers=_auth(),
        )
    assert r.status_code == 422
    assert r.json() == {"code": "document_timeout", "message": "O documento demorou demais para ser lido."}


async def test_post_oversized_returns_413(pool, api_settings) -> None:
    data = b"x" * (MAX_UPLOAD_BYTES + 1)
    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses", files={"file": ("grande.txt", data, "text/plain")}, headers=_auth()
        )
        assert r.status_code == 413
        assert r.json()["code"] == "document_too_large"


async def test_get_unknown_uuid_returns_404_and_bad_uuid_returns_422(pool, api_settings) -> None:
    await init_db(pool)
    async with api_client(api_settings) as client:
        r = await client.get(f"/v1/analyses/{uuid.uuid4()}", headers=_auth())
        assert r.status_code == 404
        assert r.json()["code"] == "not_found"

        r = await client.get("/v1/analyses/nao-e-um-uuid", headers=_auth())
        assert r.status_code == 422


# ---------------------------------------------------------------- idempotencia do POST


class _JevCounter:
    """Conta as chamadas externas (Jev) da analise: a chamada paga que um retry nao pode repetir."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.graphs import analyze_minuta_graph

        self.calls = 0
        real = analyze_minuta_graph.call_jev

        async def counting(*args: object, **kwargs: object) -> object:
            self.calls += 1
            return await real(*args, **kwargs)

        monkeypatch.setattr(analyze_minuta_graph, "call_jev", counting)


async def _count_analyses(pool) -> int:
    return await pool.fetchval("SELECT count(*) FROM analyses")


def _txt(text: str = _MINUTA, name: str = "retry.txt") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, text.encode("utf-8"), "text/plain")}


async def test_post_without_idempotency_key_returns_422(pool, api_settings) -> None:
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    async with api_client(api_settings) as client:
        r = await client.post("/v1/analyses", files=_txt(), headers={"Authorization": f"Bearer {TOKEN}"})
    assert await _count_analyses(pool) == 0
    assert r.status_code == 422


async def test_retry_with_the_same_key_returns_the_first_analysis_without_running_again(
    pool, api_settings, monkeypatch
) -> None:
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    jev = _JevCounter(monkeypatch)
    key = str(uuid.uuid4())
    async with api_client(api_settings) as client:
        first = await client.post("/v1/analyses", files=_txt(), headers=_auth(key))
        assert first.status_code == 201, first.text
        paid_calls = jev.calls
        retry = await client.post("/v1/analyses", files=_txt(), headers=_auth(key))
    assert (await _count_analyses(pool), jev.calls) == (1, paid_calls)
    assert retry.status_code == 200
    assert retry.json() == first.json()


async def test_same_key_with_a_different_document_returns_409(pool, api_settings) -> None:
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    key = str(uuid.uuid4())
    async with api_client(api_settings) as client:
        first = await client.post("/v1/analyses", files=_txt(), headers=_auth(key))
        assert first.status_code == 201, first.text
        other = await client.post("/v1/analyses", files=_txt(_MINUTA + "\nCláusula 3ª - Do Foro."), headers=_auth(key))
    assert await _count_analyses(pool) == 1
    assert other.status_code == 409
    assert other.json()["code"] == "idempotency_key_reused"


async def test_two_concurrent_posts_with_one_key_create_one_row(pool, api_settings, monkeypatch) -> None:
    """Os dois pedidos passam juntos de toda checagem previa e disputam o INSERT: so um grava."""
    from src.graphs import analyze_minuta_graph

    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    both_read_rules = asyncio.Barrier(2)
    real_load = analyze_minuta_graph.load_rules_snapshot

    async def load_then_wait(p):
        snap = await real_load(p)
        await asyncio.wait_for(both_read_rules.wait(), 10)
        return snap

    monkeypatch.setattr(analyze_minuta_graph, "load_rules_snapshot", load_then_wait)
    key = str(uuid.uuid4())
    async with api_client(api_settings) as client:
        a, b = await asyncio.gather(
            client.post("/v1/analyses", files=_txt(), headers=_auth(key)),
            client.post("/v1/analyses", files=_txt(), headers=_auth(key)),
        )
    assert await _count_analyses(pool) == 1
    assert await pool.fetchval("SELECT count(*) FROM analysis_trail WHERE step = 'iniciar'") == 1
    assert sorted([a.status_code, b.status_code]) == [200, 201]
    assert a.json()["analysis_id"] == b.json()["analysis_id"]


# ---------------------------------------------------------------- rastreio MLflow da API


def _mlflow_settings(cap) -> Settings:
    """Settings da API com o MLflow apontando ao servidor de captura."""
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        OPENROUTER_API_KEY="",
        TYPESAFE_API_KEY="",
        LEIA_API_TOKEN=TOKEN,
        MLFLOW_TRACKING_URI=cap.mlflow_uri,
        MLFLOW_EXPERIMENT_NAME="leia-lab-teste",
    )


async def test_post_com_mlflow_grava_um_trace_tagueado_e_sem_dado_pessoal(pool, api_settings, capture) -> None:
    """Requisicao com MLflow configurado: 1 traco, tagueado com o analysis_id, so conteudo mascarado."""
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])

    async with api_client(_mlflow_settings(capture)) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("Joao-da-Silva-contrato.txt", _MINUTA.encode("utf-8"), "text/plain")},
            headers=_auth(),
        )
        assert r.status_code == 201, r.text
        aid = r.json()["analysis_id"]

    assert len(capture.mlflow_trace_ids()) == 1  # exatamente um traco por analise
    blob = capture.mlflow_blob.lower()
    tag_pos = blob.find(b"leia.analysis_id")
    assert tag_pos != -1 and aid.encode() in blob[tag_pos : tag_pos + 120]  # a tag carrega o id
    for secret in ("joao-da-silva", "carlos eduardo mendes", "999.888.777-66", "99988877766"):
        assert secret.encode() not in blob, secret  # nada do documento real chega ao MLflow
    assert b"[nome]" in blob and b"[cpf]" in blob  # o texto mascarado e o que vai

    # Apos a app descer o autolog esta desligado: rodar o grafo direto nao manda mais nada.
    capture.mlflow_bodies.clear()
    from src.graphs.analyze_minuta_graph import analyze, build_analyze_minuta_graph

    graph = build_analyze_minuta_graph(pool, api_settings)
    await analyze(graph, raw_text=_MINUTA, filename="depois-do-shutdown.txt")
    assert capture.mlflow_bodies == []


async def test_post_sem_mlflow_configurado_nao_envia_nada(pool, api_settings, capture) -> None:
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])

    async with api_client(api_settings) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("sem-mlflow.txt", _MINUTA.encode("utf-8"), "text/plain")},
            headers=_auth(),
        )
        assert r.status_code == 201, r.text
    assert capture.mlflow_bodies == []


async def test_api_sobe_e_analisa_com_o_mlflow_fora_do_ar(pool, api_settings) -> None:
    """O rastreio e opcional: MLflow inacessivel na subida nao derruba nem trava a API."""
    await use_rules(pool, _RISCOS, ["reajuste_e_indexacao"])
    down = api_settings.model_copy(update={"MLFLOW_TRACKING_URI": "http://127.0.0.1:9"})

    async with api_client(down) as client:
        r = await client.post(
            "/v1/analyses",
            files={"file": ("mlflow-fora.txt", _MINUTA.encode("utf-8"), "text/plain")},
            headers=_auth(),
        )
        assert r.status_code == 201, r.text


# ---------------------------------------------------------------- desconexao do cliente


class _FakeRequest:
    """Request de mentira: desconecta (True) na n-esima sonda."""

    def __init__(self, on_probe: int = 1) -> None:
        self._on_probe = on_probe
        self.probes = 0

    async def is_disconnected(self) -> bool:
        self.probes += 1
        return self.probes >= self._on_probe


async def test_desconexao_cancela_o_trabalho_em_andamento() -> None:
    """Cliente que vai embora: a analise e cancelada (a linha vira 'failed' pelo dono do ciclo)."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(ClientDisconnected):
        await run_disconnect_guarded(hang(), _FakeRequest(on_probe=1))
    assert started.is_set() and cancelled.is_set()


async def test_cliente_presente_deixa_o_trabalho_terminar() -> None:
    """Sem desconexao, o guardiao nao interfere: o resultado do trabalho volta inteiro."""

    async def work() -> str:
        return "resultado"

    class Never(_FakeRequest):
        async def is_disconnected(self) -> bool:
            return False

    assert await run_disconnect_guarded(work(), Never()) == "resultado"
