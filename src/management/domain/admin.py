"""Admin da Leia: CRUD nas 4 tabelas de dominio; historico, analises e trilha so leitura;
base normativa com upload (pelo ``ingest_graph`` do motor) e reindexacao dos embeddings.

Analises: o login do admin nao escreve em ``analyses`` (o banco nega por grant + gatilho), entao a
pagina "Nova analise" envia o arquivo pelo servidor a API (``POST /v1/analyses``) e cai no detalhe
da analise criada. O detalhe mostra alertas, duracao e, com MLflow configurado, o link do trace.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from src.ingest.extract import MAX_UPLOAD_BYTES
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

KB_SUFFIXES = (".txt", ".md", ".pdf", ".docx")


# ---------------------------------------------------------------- dominio (editavel)


class ThemeInline(admin.TabularInline):
    model = Theme
    extra = 0


class PromptInline(admin.TabularInline):
    model = Prompt
    extra = 0


@admin.register(MinutaType)
class MinutaTypeAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "active", "created_at")
    search_fields = ("slug", "name")
    list_filter = ("active",)
    inlines = [ThemeInline, PromptInline]


class RiskMatrixInline(admin.TabularInline):
    model = RiskMatrix
    extra = 0


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ("slug", "minuta_type", "position", "norm_ids_preview")
    list_filter = ("minuta_type",)
    search_fields = ("slug",)
    inlines = [RiskMatrixInline]

    @admin.display(description="norm_ids")
    def norm_ids_preview(self, obj: Theme) -> str:
        return ", ".join(obj.norm_ids or [])


@admin.register(RiskMatrix)
class RiskMatrixAdmin(admin.ModelAdmin):
    list_display = ("risk_id", "theme", "criticality_badge", "party", "active")
    list_filter = ("criticality", "party", "active", "theme__minuta_type")
    search_fields = ("risk_id", "description")

    @admin.display(description="criticality")
    def criticality_badge(self, obj: RiskMatrix) -> str:
        colors = {"vermelho": "#c0392b", "amarelo": "#d4ac0d", "verde": "#1e8449"}
        return format_html('<b style="color:{}">{}</b>', colors.get(obj.criticality, "#333"), obj.criticality)


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ("minuta_type", "kind", "position", "model", "active")
    list_filter = ("kind", "active", "minuta_type")
    search_fields = ("prompt_text",)


# ---------------------------------------------------------------- auditoria (so leitura)


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(DomainHistory)
class DomainHistoryAdmin(_ReadOnlyAdmin):
    list_display = ("id", "table_name", "row_id", "op", "db_user", "changed_at", "diff_preview")
    list_filter = ("table_name", "op", "db_user")
    search_fields = ("row_id",)
    date_hierarchy = "changed_at"

    @admin.display(description="antes → depois (campos alterados)")
    def diff_preview(self, obj: DomainHistory) -> str:
        old, new = obj.old_row or {}, obj.new_row or {}
        if obj.op == "UPDATE":
            changed = [k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
            return "; ".join(f"{k}: {str(old.get(k))[:40]} → {str(new.get(k))[:40]}" for k in changed)
        row = new or old
        for key in ("risk_id", "slug", "kind", "name"):
            if key in row:
                return f"{obj.op} {key}={row[key]}"
        return obj.op


class TrailInline(admin.TabularInline):
    model = AnalysisTrail
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------- nova analise (pela API)

ANALISE_SUFFIXES = (".pdf", ".docx", ".txt")
API_TIMEOUT_S = 300  # a API roda a analise inteira de forma sincrona; o gunicorn espera 330 s


class NovaAnaliseForm(forms.Form):
    file = forms.FileField(help_text="Minuta .pdf, .docx ou .txt. O nome real do arquivo não sai desta máquina.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if Path(f.name).suffix.lower() not in ANALISE_SUFFIXES:
            raise forms.ValidationError("Use .pdf, .docx ou .txt.")
        if f.size > MAX_UPLOAD_BYTES:  # o mesmo teto da API, antes de ler o arquivo na memoria
            raise forms.ValidationError("O arquivo excede o limite de tamanho permitido.")
        return f


def post_analysis(filename: str, data: bytes) -> tuple[int, dict]:
    """Envia a minuta à API (multipart, campo ``file``) e devolve ``(status, corpo JSON)``.

    Cada envio do formulário é uma análise nova: uma ``Idempotency-Key`` nova por chamada.

    Sem ``LEIA_API_TOKEN`` não faz nenhuma requisição: devolve ``(0, {})``. Falha de rede levanta
    ``httpx.HTTPError``. O nome do arquivo vai só no multipart: nunca em log, nunca na resposta.
    """
    if not settings.LEIA_API_TOKEN:
        return 0, {}
    with httpx.Client(timeout=API_TIMEOUT_S) as client:
        response = client.post(
            f"{settings.LEIA_API_URL}/v1/analyses",
            files={"file": (filename, data)},
            headers={"Authorization": f"Bearer {settings.LEIA_API_TOKEN}", "Idempotency-Key": str(uuid.uuid4())},
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, body if isinstance(body, dict) else {}


def _duracao_humana(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, s = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {s} s"
    hours, m = divmod(minutes, 60)
    return f"{hours} h {m} min"


@admin.register(Analysis)
class AnalysisAdmin(_ReadOnlyAdmin):
    list_display = ("short_id", "status", "filename_alias", "minuta_type", "matrix_version", "prompt_version", "started_at")
    list_filter = ("status", "minuta_type")
    inlines = [TrailInline]
    change_list_template = "admin/domain/analysis/change_list.html"
    fields = (
        "id", "status", "filename_alias", "minuta_type", "matrix_version", "prompt_version",
        "duracao", "alertas", "trace", "started_at", "finished_at", "text_sha256", "rules_hash",
        "domain_history_id", "params", "rules_snapshot", "report",
    )
    readonly_fields = fields  # tudo é leitura; duracao/alertas/trace são calculados

    @admin.display(description="id")
    def short_id(self, obj: Analysis) -> str:
        return str(obj.id)[:8]

    def _pode_nova(self, user) -> bool:
        return user.is_superuser or user.groups.filter(name="editor").exists()

    def get_urls(self):
        nova = [path("nova/", self.admin_site.admin_view(self.nova_view), name="domain_analysis_nova")]
        return nova + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "show_nova": self._pode_nova(request.user)}
        return super().changelist_view(request, extra_context)

    def nova_view(self, request):
        """Formulário de upload que o servidor repassa à API; quem grava é a API, não o admin."""
        if not self._pode_nova(request.user):
            raise PermissionDenied  # leitor vê a lista e o detalhe, mas não dispara análise
        erro = None
        form = NovaAnaliseForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                status, body = post_analysis(upload.name, upload.read())
            except httpx.HTTPError:
                erro = "API indisponível."
            else:
                if status == 201 and body.get("analysis_id"):
                    return redirect("admin:domain_analysis_change", body["analysis_id"])
                if status == 0:
                    erro = "Token da API ausente (defina LEIA_API_TOKEN)."
                else:
                    erro = str(body.get("message") or "API indisponível.")
        context = {
            **self.admin_site.each_context(request),
            "title": "Nova análise",
            "form": form,
            "erro": erro,
        }
        return render(request, "admin/domain/analysis/nova.html", context)

    @admin.display(description="duração")
    def duracao(self, obj: Analysis) -> str:
        if obj.finished_at is None:
            return "-"
        return _duracao_humana((obj.finished_at - obj.started_at).total_seconds())

    @admin.display(description="alertas")
    def alertas(self, obj: Analysis) -> str:
        alerts = ((obj.report or {}).get("content") or {}).get("alerts") or []
        pares = sorted({(a.get("risk_id"), a.get("severity")) for a in alerts})
        if not pares:
            return "nenhum"
        return ", ".join(f"{rid} ({sev})" for rid, sev in pares)

    @admin.display(description="trace")
    def trace(self, obj: Analysis) -> str:
        if not settings.LEIA_MLFLOW_URL:
            return "sem trace"
        from src.tracing import find_trace

        ref = find_trace(settings.LEIA_MLFLOW_URL, settings.MLFLOW_EXPERIMENT_NAME, obj.id)
        if ref is None:  # MLflow fora do ar, trace ainda no lote de envio ou filtro sem resposta
            recente = obj.finished_at and (timezone.now() - obj.finished_at).total_seconds() < 60
            return "trace sendo gravado: recarregue em alguns segundos" if recente else "sem trace"
        url = (
            f"{settings.LEIA_MLFLOW_PUBLIC_URL}/#/experiments/{ref.experiment_id}"
            f"/traces?selectedEvaluationId={ref.trace_id}"
        )
        rotulo = f"trace ({ref.duration_ms} ms)" if ref.duration_ms is not None else "trace"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, rotulo)


@admin.register(AnalysisTrail)
class AnalysisTrailAdmin(_ReadOnlyAdmin):
    list_display = ("analysis", "seq", "step", "clause_n", "score", "cutoff", "matrix_version", "cited_norms_preview")
    list_filter = ("step",)

    @admin.display(description="cited_norms")
    def cited_norms_preview(self, obj: AnalysisTrail) -> str:
        return ", ".join(obj.cited_norms or [])


# ---------------------------------------------------------------- base normativa


def run_with_pool(fn: Callable[[asyncpg.Pool], Awaitable[Any]]) -> Any:
    """Roda codigo assincrono do motor (asyncpg) no MESMO banco e login do Django."""
    cfg = connection.settings_dict

    async def go() -> Any:
        pool = await asyncpg.create_pool(
            host=cfg["HOST"], port=int(cfg["PORT"]), user=cfg["USER"], password=cfg["PASSWORD"],
            database=cfg["NAME"], min_size=1, max_size=2,
        )
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(go())


def ingest_upload(filename: str, data: bytes, *, title: str, source: str) -> str:
    """Indexa um arquivo pelo ``ingest_graph`` (mascara, segmenta, gera embeddings). Devolve o doc id.

    ``title`` vira ``kb_docs.title``: o grafo de analise acha a norma por ele, entao deve ser a
    citacao exata usada na matriz (ex.: "Lei 8.245/1991, art. 4").
    """
    from src.config import Settings
    from src.graphs.ingest_graph import build_ingest_graph, ingest

    suffix = Path(filename).suffix.lower()
    if suffix not in KB_SUFFIXES:
        raise ValueError(f"formato nao suportado: {suffix}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"  # nome neutro: o nome original nao vai a lugar nenhum
        path.write_bytes(data)

        async def go(pool: asyncpg.Pool) -> str:
            out = await ingest(build_ingest_graph(pool, Settings()), file_path=path, doc_name=title, source=source)
            return out["doc_id"]

        return run_with_pool(go)


def reindex_chunks(chunks) -> tuple[int, str]:
    """Recalcula os embeddings dos chunks (offline sem chave, como o resto do motor)."""
    from src.config import Settings
    from src.ingest.masking import mask_personal_data
    from src.rag.embeddings import embed_text

    chunks = list(chunks)
    settings = Settings()

    async def embed_all() -> list:
        # O conteudo ja foi mascarado na ingestao; mascarar de novo nao o altera e o marca como MaskedText.
        return [await embed_text(mask_personal_data(c.content), settings) for c in chunks]

    results = asyncio.run(embed_all())
    for chunk, res in zip(chunks, results, strict=True):
        chunk.embedding = res.vector
        chunk.embedding_model = res.model
        chunk.indexed_at = timezone.now()
        chunk.save(update_fields=["embedding", "embedding_model", "indexed_at"])
    return len(chunks), (results[-1].model if results else "")


class KbDocUploadForm(forms.ModelForm):
    file = forms.FileField(help_text="Arquivo .txt, .md, .pdf ou .docx. O titulo deve ser a citacao usada na matriz.")

    class Meta:
        model = KbDoc
        fields = ("title", "source")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if Path(f.name).suffix.lower() not in KB_SUFFIXES:
            raise forms.ValidationError("Use .txt, .md, .pdf ou .docx.")
        return f


@admin.register(KbDoc)
class KbDocAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "chunks_count", "created_at")
    search_fields = ("title",)
    readonly_fields = ("created_at",)
    actions = ["action_reindex"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = KbDocUploadForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        upload = form.cleaned_data["file"]
        obj.pk = ingest_upload(upload.name, upload.read(), title=obj.title, source=obj.source)

    @admin.display(description="chunks")
    def chunks_count(self, obj: KbDoc) -> int:
        return obj.chunks.count()

    @admin.action(description="Reindexar embeddings dos documentos selecionados")
    def action_reindex(self, request, queryset):
        total, model = 0, ""
        for doc in queryset:
            count, model = reindex_chunks(doc.chunks.all())
            total += count
        self.message_user(request, f"{total} chunks reindexados (modelo: {model}).")


@admin.register(KbChunk)
class KbChunkAdmin(_ReadOnlyAdmin):
    list_display = ("doc", "sequence_order", "content_preview", "embedding_model", "indexed_at")
    list_filter = ("embedding_model",)
    search_fields = ("content",)
    readonly_fields = ("doc", "content", "sequence_order", "embedding_preview")

    @admin.display(description="content")
    def content_preview(self, obj: KbChunk) -> str:
        return obj.content[:80]

    @admin.display(description="embedding")
    def embedding_preview(self, obj: KbChunk) -> str:
        if obj.embedding is None:
            return "sem embedding (reindexe o documento)"
        head = json.dumps([round(float(v), 4) for v in list(obj.embedding)[:5]])
        return f"VECTOR({len(obj.embedding)}) = {head}..."
