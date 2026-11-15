"""Testes do protótipo B4 contra o schema real da F (aplicado uma vez por sessão).

Requer Postgres com pgvector (DATABASE_URL; padrão: container local 5433).
Rodar: uv run python -m src.management.manage test src.management.domain
"""

import asyncio
from pathlib import Path

from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from src.management.domain.admin import chunk_text, extract_text, reindex_chunks
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


class SchemaMixin:
    """Aplica corpus + foundation schema uma única vez (DDL idempotente).

    O DDL roda ANTES de super().setUpClass(): as classes TestCase abrem
    atomics de classe e o rollback desfaria o DDL se ele rodasse dentro.
    """

    _applied = False

    @classmethod
    def setUpClass(cls):
        if not SchemaMixin._applied:
            with connection.cursor() as cursor:
                cursor.execute((REPO_ROOT / "src" / "db" / "schema.sql").read_text("utf-8"))
                cursor.execute(
                    (REPO_ROOT / "src" / "foundation" / "schema.sql").read_text("utf-8")
                )
            SchemaMixin._applied = True
        super().setUpClass()


class DomainCrudHistoryTests(SchemaMixin, TestCase):
    def test_insert_update_grava_domain_history_com_db_user(self):
        mtype = MinutaType.objects.create(
            slug="t-b4", name="Tipo B4", classifier_description="desc"
        )
        theme = Theme.objects.create(minuta_type=mtype, slug="tema-b4", position=0)
        risk = RiskMatrix.objects.create(
            theme=theme, risk_id="R-B4", description="d", criticality="amarelo"
        )
        rows = list(DomainHistory.objects.filter(table_name="risk_matrix", row_id=risk.id))
        self.assertEqual([r.op for r in rows], ["INSERT"])
        self.assertTrue(all(r.db_user for r in rows))

        risk.criticality = "vermelho"
        risk.save()
        ops = list(
            DomainHistory.objects.filter(table_name="risk_matrix", row_id=risk.id)
            .order_by("id")
            .values_list("op", flat=True)
        )
        self.assertEqual(ops, ["INSERT", "UPDATE"])

    def test_prompt_unique_no_banco(self):
        mtype = MinutaType.objects.create(
            slug="t-uniq", name="T", classifier_description="desc"
        )
        Prompt.objects.create(minuta_type=mtype, kind="triagem_risco", position=0, prompt_text="x")
        with self.assertRaises(Exception):
            Prompt.objects.create(
                minuta_type=mtype, kind="triagem_risco", position=0, prompt_text="y"
            )

    def test_history_rejeita_delete(self):
        mtype = MinutaType.objects.create(
            slug="t-hist1", name="T", classifier_description="desc"
        )
        with connection.cursor() as cursor:
            with self.assertRaises(Exception) as ctx:
                cursor.execute("DELETE FROM domain_history")
            self.assertIn("append-only", str(ctx.exception))

    def test_history_rejeita_update(self):
        MinutaType.objects.create(slug="t-hist2", name="T", classifier_description="desc")
        with connection.cursor() as cursor:
            with self.assertRaises(Exception) as ctx:
                cursor.execute("UPDATE domain_history SET op = 'X'")
            self.assertIn("append-only", str(ctx.exception))


def _load_snapshot():
    """load_rules_snapshot via pool asyncpg próprio (fora da transação do TestCase)."""
    import asyncpg

    from src.foundation.rules import load_rules_snapshot

    cfg = connection.settings_dict

    async def _go():
        pool = await asyncpg.create_pool(
            host=cfg["HOST"],
            port=int(cfg["PORT"]),
            user=cfg["USER"],
            password=cfg["PASSWORD"],
            database=cfg["NAME"],
        )
        try:
            return await load_rules_snapshot(pool)
        finally:
            await pool.close()

    return asyncio.run(_go())


class HashVersionTests(SchemaMixin, TransactionTestCase):
    """Editar um risco muda matrix_version — a próxima análise usa a regra nova."""

    def _fixture_teardown(self):  # TRUNCATE é bloqueado pelos triggers append-only
        pass

    def tearDown(self):
        RiskMatrix.objects.filter(risk_id="R-H1").delete()
        Theme.objects.filter(slug="tema-hash").delete()
        MinutaType.objects.filter(slug="t-hash").delete()

    def test_editar_risco_muda_matrix_version(self):
        mtype = MinutaType.objects.create(
            slug="t-hash", name="T", classifier_description="desc classificador"
        )
        theme = Theme.objects.create(minuta_type=mtype, slug="tema-hash", position=0)
        risk = RiskMatrix.objects.create(
            theme=theme, risk_id="R-H1", description="d1", criticality="verde"
        )

        snap1 = _load_snapshot()
        self.assertEqual(snap1.matrix_version, snap1.matrix_version)

        risk.criticality = "vermelho"
        risk.save()
        snap2 = _load_snapshot()

        self.assertNotEqual(snap1.matrix_version, snap2.matrix_version)
        cores = [
            r["cor"]
            for riscos in snap2.content["types"]["t-hash"]["riscos"].values()
            for r in riscos
        ]
        self.assertEqual(cores, ["vermelho"])


class KbTests(SchemaMixin, TestCase):
    def test_upload_chunks_e_reindex_offline(self):
        doc = KbDoc.objects.create(title="Doc B4", source="kb")
        content = "Parágrafo um sobre locação.\n\n" + "Continuação do texto normativo. " * 80
        for order, part in enumerate(chunk_text(content)):
            KbChunk.objects.create(doc=doc, content=part, sequence_order=order)

        chunks = list(doc.chunks.all())
        self.assertGreaterEqual(len(chunks), 1)

        count, model = reindex_chunks(KbChunk.objects.filter(doc=doc))
        self.assertEqual(count, len(chunks))
        self.assertEqual(model, "offline-hash-v1")
        for chunk in chunks:
            chunk.refresh_from_db()
            self.assertIsNotNone(chunk.embedding)
            self.assertEqual(len(chunk.embedding), 1536)
            self.assertEqual(chunk.embedding_model, "offline-hash-v1")

    def test_tsv_content_gerada_pelo_banco(self):
        doc = KbDoc.objects.create(title="Doc TSV", source="kb")
        KbChunk.objects.create(
            doc=doc, content="Locação residencial com cláusula especial", sequence_order=0
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tsv_content::text FROM kb_chunks WHERE doc_id = %s", [str(doc.id)]
            )
            row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertIn("loca", row[0])

    def test_extract_text_txt(self):
        text = extract_text("arquivo.txt", "conteúdo".encode("utf-8"))
        self.assertEqual(text, "conteúdo")


class AdminSmokeTests(SchemaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin-b4", "b4@example.com", "proto-pass-1")

    def test_admin_exibe_todas_as_tabelas(self):
        self.client.force_login(self.admin)
        for model in (
            MinutaType,
            Theme,
            RiskMatrix,
            Prompt,
            DomainHistory,
            Analysis,
            AnalysisTrail,
            KbDoc,
            KbChunk,
        ):
            url = reverse(f"admin:domain_{model._meta.model_name}_changelist")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn(model, site._registry)

    def test_admin_bloqueia_escrita_nos_auditaveis(self):
        self.client.force_login(self.admin)
        for model in (DomainHistory, Analysis, AnalysisTrail):
            model_admin = site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))

    def test_kbdoc_add_form_com_upload(self):
        self.client.force_login(self.admin)
        url = reverse("admin:domain_kbdoc_add")
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("norma.txt", "Texto da norma.\n\nSegunda parte.".encode())
        response = self.client.post(
            url, {"title": "Norma 1", "source": "kb", "file": upload}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(KbDoc.objects.filter(title="Norma 1").exists())
        doc = KbDoc.objects.get(title="Norma 1")
        self.assertGreaterEqual(doc.chunks.count(), 1)
