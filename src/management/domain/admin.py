"""Admin do protótipo B4: CRUD nas 4 tabelas de domínio; auditáveis só leitura;
base normativa com upload e reindexação (embeddings, offline sem chave)."""

import asyncio
import json
from pathlib import Path

from django import forms
from django.contrib import admin
from django.db import connection
from django.utils import timezone
from django.utils.html import format_html

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
        return format_html(
            '<b style="color:{}">{}</b>', colors.get(obj.criticality, "#333"), obj.criticality
        )


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ("minuta_type", "kind", "position", "model", "active")
    list_filter = ("kind", "active", "minuta_type")
    search_fields = ("prompt_text",)


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
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

    @admin.display(description="old → new (resumo)")
    def diff_preview(self, obj: DomainHistory) -> str:
        def brief(row: dict | None) -> str:
            if not row:
                return "∅"
            keys = ("risk_id", "slug", "kind", "criticality", "name")
            for key in keys:
                if key in row:
                    return f"{key}={row[key]}"
            return f"{len(row)} campos"

        return f"{brief(obj.old_row)} → {brief(obj.new_row)}"


class TrailInline(admin.TabularInline):
    model = AnalysisTrail
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Analysis)
class AnalysisAdmin(_ReadOnlyAdmin):
    list_display = (
        "short_id",
        "status",
        "filename_alias",
        "minuta_type",
        "matrix_version",
        "prompt_version",
        "started_at",
    )
    list_filter = ("status", "minuta_type")
    inlines = [TrailInline]

    @admin.display(description="id")
    def short_id(self, obj: Analysis) -> str:
        return str(obj.id)[:8]


@admin.register(AnalysisTrail)
class AnalysisTrailAdmin(_ReadOnlyAdmin):
    list_display = (
        "analysis",
        "seq",
        "step",
        "clause_n",
        "score",
        "cutoff",
        "matrix_version",
        "cited_norms_preview",
    )
    list_filter = ("step",)

    @admin.display(description="cited_norms")
    def cited_norms_preview(self, obj: AnalysisTrail) -> str:
        return ", ".join(obj.cited_norms or [])


# ---------------------------------------------------------------- base normativa


def extract_text(filename: str, data: bytes) -> str:
    """Texto bruto de .txt/.md/.pdf/.docx (deps já existentes no projeto)."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md"):
        return data.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        import io

        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    raise ValueError(f"Formato não suportado: {suffix}")


def chunk_text(text: str, size: int = 900, overlap: int = 100) -> list[str]:
    """Chunks por parágrafos acumulados (~size), com overlap simples."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + paragraph if overlap else paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def reindex_chunks(chunks) -> tuple[int, str]:
    """(re)calcula embeddings dos chunks via src.rag.embeddings (offline sem chave)."""
    from src.config import Settings
    from src.rag.embeddings import embed_text

    settings = Settings()
    count = 0
    model = ""
    for chunk in chunks:
        result = asyncio.run(embed_text(chunk.content, settings))
        chunk.embedding = result.vector
        chunk.embedding_model = result.model
        chunk.indexed_at = timezone.now()
        chunk.save(update_fields=["embedding", "embedding_model", "indexed_at"])
        count += 1
        model = result.model
    return count, model


class KbDocForm(forms.ModelForm):
    file = forms.FileField(help_text="Arquivo .txt, .md, .pdf ou .docx (gera os chunks).")

    class Meta:
        model = KbDoc
        fields = ("title", "source")


@admin.register(KbDoc)
class KbDocAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "chunks_count", "created_at")
    search_fields = ("title",)
    readonly_fields = ("created_at",)
    actions = ["action_reindex"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = KbDocForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj._uploaded = form.cleaned_data["file"]
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if not change:
            uploaded = form.instance._uploaded
            text = extract_text(uploaded.name, uploaded.read())
            for order, part in enumerate(chunk_text(text)):
                KbChunk.objects.create(doc=form.instance, content=part, sequence_order=order)

    @admin.display(description="chunks")
    def chunks_count(self, obj: KbDoc) -> int:
        return obj.chunks.count()

    @admin.action(description="Reindexar embeddings dos chunks selecionados")
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
    readonly_fields = ("doc", "content", "sequence_order", "embedding_preview", "tsv_preview")

    @admin.display(description="content")
    def content_preview(self, obj: KbChunk) -> str:
        return obj.content[:80]

    @admin.display(description="tsvector (texto)")
    def tsv_preview(self, obj: KbChunk) -> str:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tsv_content::text FROM kb_chunks WHERE id = %s", [str(obj.id)]
            )
            row = cursor.fetchone()
        return row[0] if row else "—"

    @admin.display(description="embedding")
    def embedding_preview(self, obj: KbChunk) -> str:
        if obj.embedding is None:
            return "sem embedding (reindexe o doc)"
        dims = len(obj.embedding)
        head = json.dumps([round(float(v), 4) for v in list(obj.embedding)[:5]])
        return f"VECTOR({dims}) = {head}..."
