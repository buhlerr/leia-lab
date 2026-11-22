"""Testes do admin contra o schema real (src/db/schema.sql aplicado uma vez por sessao).

Requer Postgres com pgvector (DATABASE_URL; o Django cria e apaga ``test_<banco>``).
Rodar: uv run python -m src.management.manage test src.management.domain
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock
from uuid import uuid4

import httpx
from django import forms
from django.contrib.admin.sites import site
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

import src.management.domain.admin as domain_admin
from src.management.domain.admin import reindex_chunks, run_with_pool
from src.management.domain.models import (
    Analysis,
    AnalysisTrail,
    DomainHistory,
    KbChunk,
    KbDoc,
    MinutaType,
    Prompt,
    RiskMatrix,
    Theme,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALL_MODELS = (MinutaType, Theme, RiskMatrix, Prompt, DomainHistory, Analysis, AnalysisTrail, KbDoc, KbChunk)
AUDIT_MODELS = (DomainHistory, Analysis, AnalysisTrail)
MINUTA = (
    "CONTRATO DE LOCAÇÃO RESIDENCIAL\n"
    "Cláusula 1ª - Do Prazo e Valor: A locação inicia em 01/04/2026 pelo prazo de 30 meses, "
    "com aluguel mensal de R$ 2.800,00 e demais encargos ajustados entre as partes.\n"
    "Cláusula 2ª - Das Benfeitorias: O locatário renuncia a qualquer indenização por benfeitorias, "
    "inclusive as necessárias, conforme ajustado entre as partes neste instrumento contratual."
)


class SchemaMixin:
    """Aplica o DDL da Leia uma vez (idempotente), ANTES do atomic de classe do TestCase."""

    _applied = False

    @classmethod
    def setUpClass(cls):
        if not SchemaMixin._applied:
            with connection.cursor() as cursor:
                cursor.execute((REPO_ROOT / "src" / "db" / "schema.sql").read_text("utf-8"))
            SchemaMixin._applied = True
        super().setUpClass()


def _user(name: str, group: str | None = None, superuser: bool = False) -> User:
    if superuser:
        return User.objects.create_superuser(name, f"{name}@exemplo.invalid", "senha-de-teste-123")
    u = User.objects.create_user(name, f"{name}@exemplo.invalid", "senha-de-teste-123", is_staff=True)
    if group:
        u.groups.add(Group.objects.get(name=group))
    return u


def _change_form_data(response) -> dict:
    """POST de um formulario de alteracao do admin, igual ao que o navegador mandaria sem editar nada."""
    data: dict = {}

    def add(form) -> None:
        for bf in form:
            value = bf.value()  # ja vem no formato do widget (JSON/array serializados): nao preparar de novo
            if isinstance(bf.field, forms.BooleanField):
                if value:
                    data[bf.html_name] = "on"
            elif value is not None:
                data[bf.html_name] = value

    add(response.context["adminform"].form)
    for inline in response.context["inline_admin_formsets"]:
        fs = inline.formset
        add(fs.management_form)
        for form in fs.forms:
            add(form)
    return data


def _admin_edit(client, obj, **changes) -> None:
    url = reverse(f"admin:domain_{obj._meta.model_name}_change", args=[obj.pk])
    data = _change_form_data(client.get(url))
    data.update(changes)
    resp = client.post(url, data)
    assert resp.status_code == 302, getattr(resp.context.get("adminform"), "errors", resp.status_code)


# ---------------------------------------------------------------- historico e banco


class DomainCrudHistoryTests(SchemaMixin, TestCase):
    def test_insert_update_grava_domain_history_com_db_user(self):
        mtype = MinutaType.objects.create(slug="t-crud", name="Tipo", classifier_description="desc")
        theme = Theme.objects.create(minuta_type=mtype, slug="tema-crud", position=0)
        risk = RiskMatrix.objects.create(theme=theme, risk_id="R-CRUD", description="d", criticality="amarelo")
        risk.criticality = "vermelho"
        risk.save()
        rows = list(DomainHistory.objects.filter(table_name="risk_matrix", row_id=risk.id).order_by("id"))
        self.assertEqual([r.op for r in rows], ["INSERT", "UPDATE"])
        self.assertEqual({r.db_user for r in rows}, {connection.settings_dict["USER"]})
        self.assertEqual((rows[1].old_row["criticality"], rows[1].new_row["criticality"]), ("amarelo", "vermelho"))

    def test_prompt_unique_no_banco(self):
        mtype = MinutaType.objects.create(slug="t-uniq", name="T", classifier_description="desc")
        Prompt.objects.create(minuta_type=mtype, kind="triagem_risco", position=0, prompt_text="x")
        with self.assertRaises(Exception):
            Prompt.objects.create(minuta_type=mtype, kind="triagem_risco", position=0, prompt_text="y")

    def test_history_rejeita_delete(self):
        MinutaType.objects.create(slug="t-hist1", name="T", classifier_description="desc")
        with connection.cursor() as cursor, self.assertRaises(Exception) as ctx:
            cursor.execute("DELETE FROM domain_history")
        self.assertIn("append-only", str(ctx.exception))

    def test_history_rejeita_update(self):
        MinutaType.objects.create(slug="t-hist2", name="T", classifier_description="desc")
        with connection.cursor() as cursor, self.assertRaises(Exception) as ctx:
            cursor.execute("UPDATE domain_history SET op = 'X'")
        self.assertIn("append-only", str(ctx.exception))


class SchemaOwnershipTests(SchemaMixin, TestCase):
    """O Django nunca e dono do DDL da Leia (duas 'donas' do schema = risco da M3)."""

    def test_todos_os_models_sao_managed_false(self):
        self.assertTrue(all(not m._meta.managed for m in ALL_MODELS))

    def test_migracoes_do_app_nao_geram_ddl(self):
        for name in ("0001_initial", "0002_groups"):
            out = StringIO()
            call_command("sqlmigrate", "domain", name, stdout=out)
            sql = out.getvalue().upper()
            self.assertNotIn("CREATE TABLE", sql, name)
            self.assertNotIn("ALTER TABLE", sql, name)
            self.assertNotIn("DROP", sql, name)


# ---------------------------------------------------------------- criterio de aceite


class EditorChangesReachNextAnalysisTests(SchemaMixin, TransactionTestCase):
    """Uma pessoa do grupo editor muda risco, tema e prompt PELO ADMIN; a proxima analise usa."""

    def _fixture_teardown(self):  # TRUNCATE e bloqueado pelos gatilhos append-only
        User.objects.filter(username="editora-aceite").delete()

    def setUp(self):
        from src.db.seed import seed_defaults

        run_with_pool(seed_defaults)
        # Estado conhecido, independente de outros testes que tenham editado o seed.
        RiskMatrix.objects.filter(risk_id="R-04").update(criticality="amarelo")
        Theme.objects.filter(slug="benfeitorias_e_conservacao").update(description=None)
        from src.db.defaults import SISTEMA_REDIGIR

        Prompt.objects.filter(kind="redigir_system").update(prompt_text=SISTEMA_REDIGIR)

    def _analyze(self) -> tuple[dict, list[dict], list[str]]:
        import src.graphs.analyze_minuta_graph as g
        from src.config import Settings

        cfg = connection.settings_dict
        settings = Settings(
            DATABASE_URL=f"postgresql://{cfg['USER']}:{cfg['PASSWORD']}@{cfg['HOST']}:{cfg['PORT']}/{cfg['NAME']}",
            OPENROUTER_API_KEY="",
            TYPESAFE_API_KEY="",
        )
        questions: list[dict] = []
        systems: list[str] = []
        real_jev, real_llm = g.call_jev, g.chat_completion

        async def jev(state, q, s=None):
            questions.append(q)
            return await real_jev(state, q, s)

        async def llm(system, user, s=None, **kw):
            systems.append(system)
            return await real_llm(system, user, s, **kw)

        with mock.patch.object(g, "call_jev", jev), mock.patch.object(g, "chat_completion", llm):
            out = run_with_pool(
                lambda pool: g.analyze(g.build_analyze_minuta_graph(pool, settings), raw_text=MINUTA, filename="m.txt")
            )
        return out, questions, systems

    def test_editor_muda_risco_tema_e_prompt_e_a_proxima_analise_usa(self):
        before, _, _ = self._analyze()
        sev = {a["risk_id"]: a["severity"] for a in before["report_envelope"]["content"]["alerts"]}
        self.assertEqual(sev["R-04"], "yellow")

        editor = _user("editora-aceite", group="editor")
        self.assertFalse(editor.is_superuser)
        self.client.force_login(editor)
        _admin_edit(self.client, RiskMatrix.objects.get(risk_id="R-04"), criticality="vermelho")
        _admin_edit(self.client, Theme.objects.get(slug="benfeitorias_e_conservacao"), description="Benfeitorias (v2)")
        novo = "REDATOR v2: responda com alertas em JSON."
        _admin_edit(self.client, Prompt.objects.get(kind="redigir_system"), prompt_text=novo)

        after, questions, systems = self._analyze()
        sev = {a["risk_id"]: a["severity"] for a in after["report_envelope"]["content"]["alerts"]}
        self.assertEqual(sev["R-04"], "red")  # risco
        temas = [q["tema"]["criteria"] for q in questions if "tema" in q]
        self.assertTrue(temas and all(t["benfeitorias_e_conservacao"] == "Benfeitorias (v2)" for t in temas))  # tema
        self.assertTrue(systems and set(systems) == {novo})  # prompt
        a1, a2 = (Analysis.objects.get(pk=x["analysis_id"]) for x in (before, after))
        self.assertNotEqual(a1.matrix_version, a2.matrix_version)
        self.assertNotEqual(a1.prompt_version, a2.prompt_version)

        # historico: quem (login do banco) e o antes/depois de cada uma das 3 edicoes, entre as duas analises
        changes = DomainHistory.objects.filter(id__gt=a1.domain_history_id, id__lte=a2.domain_history_id, op="UPDATE")
        by_table = {h.table_name: h for h in changes}
        self.assertEqual(set(by_table), {"risk_matrix", "themes", "prompts"})
        self.assertEqual({h.db_user for h in changes}, {connection.settings_dict["USER"]})
        self.assertEqual(
            (by_table["risk_matrix"].old_row["criticality"], by_table["risk_matrix"].new_row["criticality"]),
            ("amarelo", "vermelho"),
        )
        self.assertEqual(by_table["prompts"].new_row["prompt_text"], novo)


# ---------------------------------------------------------------- grupos e admin


class GroupPermissionTests(SchemaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mtype = MinutaType.objects.create(slug="t-perm", name="T", classifier_description="desc")
        theme = Theme.objects.create(minuta_type=cls.mtype, slug="tema-perm", position=0)
        cls.risk = RiskMatrix.objects.create(theme=theme, risk_id="R-P", description="d", criticality="verde")
        cls.leitor = _user("leitor-1", group="leitor")
        cls.editor = _user("editor-1", group="editor")

    def test_leitor_ve_tudo_e_nao_altera_nada(self):
        self.client.force_login(self.leitor)
        for model in ALL_MODELS:
            url = reverse(f"admin:domain_{model._meta.model_name}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, url)
        # formulario COMPLETO e valido (o mesmo que o editor mandaria): so a permissao pode barrar.
        self.client.force_login(self.editor)
        url = reverse("admin:domain_riskmatrix_change", args=[self.risk.pk])
        data = {**_change_form_data(self.client.get(url)), "criticality": "vermelho"}
        self.client.force_login(self.leitor)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.risk.refresh_from_db()
        self.assertEqual(self.risk.criticality, "verde")
        self.assertEqual(self.client.get(reverse("admin:domain_riskmatrix_add")).status_code, 403)

    def test_editor_nao_escreve_em_auditoria(self):
        self.client.force_login(self.editor)
        for model in AUDIT_MODELS:
            self.assertEqual(self.client.get(reverse(f"admin:domain_{model._meta.model_name}_add")).status_code, 403)
        hist = DomainHistory.objects.filter(table_name="risk_matrix", row_id=self.risk.id).first()
        resp = self.client.post(reverse("admin:domain_domainhistory_delete", args=[hist.pk]), {"post": "yes"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(DomainHistory.objects.filter(pk=hist.pk).exists())


class AdminSmokeTests(SchemaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("admin-smoke", superuser=True)

    def test_admin_exibe_todas_as_tabelas(self):
        self.client.force_login(self.admin)
        for model in ALL_MODELS:
            url = reverse(f"admin:domain_{model._meta.model_name}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, url)
            self.assertIn(model, site._registry)

    def test_admin_bloqueia_escrita_nos_auditaveis(self):
        for model in AUDIT_MODELS:
            model_admin = site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))


# ---------------------------------------------------------------- nova analise (pela API)


def _analysis(**extra) -> Analysis:
    """Uma analise pronta para o detalhe: dois alertas e duracao de ~95 s."""
    base: dict = dict(
        id=uuid4(),
        status="done",
        filename_alias="documento-ab12cd34.txt",
        text_sha256="h" * 64,
        params={},
        rules_snapshot={},
        rules_hash="h" * 12,
        matrix_version="v1",
        prompt_version="p1",
        domain_history_id=1,
        minuta_type="locacao_residencial",
        report={
            "content": {
                "alerts": [
                    {"risk_id": "R-02", "severity": "yellow", "clause_index": 5},
                    {"risk_id": "R-01", "severity": "red", "clause_index": 2},
                ]
            }
        },
        started_at=timezone.now() - timedelta(seconds=95),
        finished_at=timezone.now(),
    )
    base.update(extra)
    return Analysis.objects.create(**base)


class NovaAnaliseTests(SchemaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.leitor = _user("leitor-nova", group="leitor")
        cls.editor = _user("editor-nova", group="editor")

    def test_editor_abre_o_formulario(self):
        self.client.force_login(self.editor)
        resp = self.client.get(reverse("admin:domain_analysis_nova"))
        self.assertEqual(resp.status_code, 200)
        corpo = resp.content.decode()
        self.assertIn("Nova análise", corpo)
        self.assertIn('enctype="multipart/form-data"', corpo)

    def test_editor_envia_e_cai_no_detalhe_da_analise(self):
        alvo = _analysis()
        self.client.force_login(self.editor)
        upload = SimpleUploadedFile("Minuta-do-Carlos.txt", b"CONTRATO DE LOCACAO")
        with mock.patch.object(domain_admin, "post_analysis", return_value=(201, {"analysis_id": str(alvo.id)})) as post:
            resp = self.client.post(reverse("admin:domain_analysis_nova"), {"file": upload})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("admin:domain_analysis_change", args=[alvo.id]))
        self.assertEqual(post.call_count, 1)

    def test_leitor_recebe_403_ao_enviar_e_ao_abrir(self):
        self.client.force_login(self.leitor)
        url = reverse("admin:domain_analysis_nova")
        self.assertEqual(self.client.get(url).status_code, 403)
        upload = SimpleUploadedFile("minuta.txt", b"CONTRATO DE LOCACAO")
        self.assertEqual(self.client.post(url, {"file": upload}).status_code, 403)

    def test_erro_da_api_aparece_e_o_nome_do_arquivo_nunca(self):
        self.client.force_login(self.editor)
        upload = SimpleUploadedFile("Minuta-do-Carlos-Mendes.txt", b"CONTRATO DE LOCACAO")
        erro_api = {"code": "invalid_document", "message": "O documento enviado não pode ser lido."}
        with mock.patch.object(domain_admin, "post_analysis", return_value=(422, erro_api)):
            resp = self.client.post(reverse("admin:domain_analysis_nova"), {"file": upload})
        self.assertEqual(resp.status_code, 200)  # formulario volta com a mensagem da API
        corpo = resp.content.decode()
        self.assertIn("O documento enviado não pode ser lido.", corpo)
        self.assertNotIn("Minuta-do-Carlos-Mendes", corpo)

    def test_erro_de_rede_mostra_mensagem_fixa(self):
        self.client.force_login(self.editor)
        upload = SimpleUploadedFile("minuta.txt", b"CONTRATO DE LOCACAO")
        with mock.patch.object(domain_admin, "post_analysis", side_effect=httpx.ConnectError("boom")):
            resp = self.client.post(reverse("admin:domain_analysis_nova"), {"file": upload})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("API indisponível", resp.content.decode())

    def test_sem_token_mensagem_fixa_e_sem_requisicao(self):
        self.client.force_login(self.editor)
        upload = SimpleUploadedFile("Minuta-do-Carlos.txt", b"CONTRATO DE LOCACAO")
        with override_settings(LEIA_API_TOKEN=""):
            resp = self.client.post(reverse("admin:domain_analysis_nova"), {"file": upload})
        self.assertEqual(resp.status_code, 200)  # formulario volta com mensagem fixa
        corpo = resp.content.decode()
        self.assertIn("LEIA_API_TOKEN", corpo)
        self.assertNotIn("Minuta-do-Carlos", corpo)
        # direto da funcao de envio: sem token nao ha requisicao (uma tentativa falharia alto)
        with override_settings(LEIA_API_TOKEN=""):
            self.assertEqual(domain_admin.post_analysis("a.txt", b"x"), (0, {}))
        # sufixo invalido: o formulario barra antes de qualquer chamada
        upload_x = SimpleUploadedFile("planilha.xlsx", b"x")
        with mock.patch.object(domain_admin, "post_analysis") as post_x:
            resp = self.client.post(reverse("admin:domain_analysis_nova"), {"file": upload_x})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Use .pdf, .docx ou .txt.", resp.content.decode())
        post_x.assert_not_called()

    def test_botao_nova_analise_no_changelist_so_para_editor(self):
        self.client.force_login(self.editor)
        corpo = self.client.get(reverse("admin:domain_analysis_changelist")).content.decode()
        self.assertIn(reverse("admin:domain_analysis_nova"), corpo)
        self.client.force_login(self.leitor)
        corpo = self.client.get(reverse("admin:domain_analysis_changelist")).content.decode()
        self.assertNotIn(reverse("admin:domain_analysis_nova"), corpo)


class AnalysisDetailTests(SchemaMixin, TestCase):
    def test_detalhe_mostra_alertas_duracao_e_sem_trace(self):
        self.client.force_login(_user("leitor-detalhe", group="leitor"))
        with override_settings(LEIA_MLFLOW_URL=""):
            a = _analysis()
            resp = self.client.get(reverse("admin:domain_analysis_change", args=[a.id]))
            self.assertEqual(resp.status_code, 200)
            corpo = resp.content.decode()
            self.assertIn("R-01 (red)", corpo)
            self.assertIn("R-02 (yellow)", corpo)
            self.assertIn("1 min 35 s", corpo)
            self.assertIn("sem trace", corpo)

            correndo = _analysis(status="running", finished_at=None, report=None, minuta_type=None)
            resp = self.client.get(reverse("admin:domain_analysis_change", args=[correndo.id]))
            self.assertEqual(resp.status_code, 200)
            detalhe = site._registry[Analysis]
            self.assertEqual(detalhe.duracao(correndo), "-")
            self.assertEqual(detalhe.alertas(correndo), "nenhum")


# ---------------------------------------------------------------- base normativa


class KbTests(SchemaMixin, TransactionTestCase):
    def _fixture_teardown(self):
        KbDoc.objects.filter(title__startswith="Teste KB").delete()
        User.objects.filter(username="editor-kb").delete()

    def test_upload_pelo_admin_passa_pelo_ingest_mascara_e_indexa(self):
        self.client.force_login(_user("editor-kb", group="editor"))
        content = "Art. 4 Durante o prazo estipulado...\n\nContato do autor: Joao da Silva, CPF 123.456.789-09.\n"
        upload = SimpleUploadedFile("arquivo_original_Joao.txt", content.encode())
        resp = self.client.post(
            reverse("admin:domain_kbdoc_add"), {"title": "Teste KB Lei 8.245/1991, art. 4", "source": "kb", "file": upload}
        )
        self.assertEqual(resp.status_code, 302)
        doc = KbDoc.objects.get(title="Teste KB Lei 8.245/1991, art. 4")  # titulo = citacao, nao o nome do arquivo
        chunks = list(doc.chunks.all())
        self.assertTrue(chunks)
        text = " ".join(c.content for c in chunks)
        self.assertIn("[CPF]", text)
        self.assertNotIn("123.456.789-09", text)
        self.assertTrue(all(c.embedding is not None and c.embedding_model for c in chunks))
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM kb_docs WHERE title ILIKE %s OR metadata::text ILIKE %s", ["%original_Joao%"] * 2)
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_upload_recusa_formato_desconhecido(self):
        self.client.force_login(_user("editor-kb", group="editor"))
        upload = SimpleUploadedFile("planilha.xlsx", b"x")
        resp = self.client.post(reverse("admin:domain_kbdoc_add"), {"title": "Teste KB xlsx", "source": "kb", "file": upload})
        self.assertEqual(resp.status_code, 200)  # formulario volta com erro
        self.assertFalse(KbDoc.objects.filter(title="Teste KB xlsx").exists())

    def test_reindex_offline(self):
        doc = KbDoc.objects.create(title="Teste KB reindex", source="kb")
        KbChunk.objects.create(doc=doc, content="Locação residencial com cláusula especial", sequence_order=0)
        count, model = reindex_chunks(doc.chunks.all())
        self.assertEqual((count, model), (1, "offline-hash-v1"))
        chunk = doc.chunks.get()
        self.assertEqual((len(chunk.embedding), chunk.embedding_model), (1536, "offline-hash-v1"))
        with connection.cursor() as cursor:  # tsv_content continua gerada pelo banco
            cursor.execute("SELECT tsv_content::text FROM kb_chunks WHERE id = %s", [str(chunk.id)])
            self.assertIn("loca", cursor.fetchone()[0])


# ---------------------------------------------------------------- configuracao


class SettingsTests(TestCase):
    def test_sem_secret_key_fora_de_dev_o_admin_nao_sobe(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG")}
        proc = subprocess.run(
            [sys.executable, "-c", "import src.management.leia_admin.settings"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", proc.stderr)

    def test_atras_do_proxy_https_confia_no_forwarded_proto_e_usa_cookies_secure(self):
        code = (
            "from src.management.leia_admin import settings as s; "
            "print(getattr(s, 'SECURE_PROXY_SSL_HEADER', None), getattr(s, 'SESSION_COOKIE_SECURE', False), "
            "getattr(s, 'CSRF_COOKIE_SECURE', False))"
        )
        base = {k: v for k, v in os.environ.items() if k != "DJANGO_BEHIND_HTTPS_PROXY"}
        base["DJANGO_SECRET_KEY"] = "x" * 50
        out = {}
        for flag in ("", "true"):
            env = {**base, **({"DJANGO_BEHIND_HTTPS_PROXY": flag} if flag else {})}
            proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
            out[flag] = proc.stdout.strip()
        self.assertEqual(out[""], "None False False")  # padrao: nao confia em cabecalho de proxy
        self.assertEqual(out["true"], "('HTTP_X_FORWARDED_PROTO', 'https') True True")

    def test_hosts_padrao_so_localhost(self):
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_ALLOWED_HOSTS"}
        env["DJANGO_SECRET_KEY"] = "x" * 50
        proc = subprocess.run(
            [sys.executable, "-c", "from src.management.leia_admin import settings as s; print(s.ALLOWED_HOSTS)"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True,
        )
        self.assertEqual(proc.stdout.strip(), "['localhost', '127.0.0.1']")



class RootRedirectTests(SimpleTestCase):
    def test_raiz_redireciona_para_o_admin(self):
        # O SSO do Pangolin devolve para https://admin.rauvbr.com/; a raiz nao pode dar 404.
        response = self.client.get("/")
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
