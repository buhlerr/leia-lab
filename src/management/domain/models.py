"""Models sobre as tabelas da Leia (DDL em src/db/schema.sql, aplicado por ``init_db``).

Todos ``managed=False``: o DDL e do ``schema.sql``, nunca do Django. O ``migrate`` do Django so
cria as tabelas ``django_*``/``auth_*`` (ver tests: nenhuma migracao deste app gera SQL).
As 4 tabelas de dominio sao editaveis; historico, analises e trilha sao so leitura
(o banco tambem nega, por grant e por gatilho).
"""

from uuid import uuid4

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


class MinutaType(models.Model):
    id = models.BigAutoField(primary_key=True)
    slug = models.TextField(unique=True)
    name = models.TextField()
    classifier_description = models.TextField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        managed = False
        db_table = "minuta_types"

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Theme(models.Model):
    id = models.BigAutoField(primary_key=True)
    minuta_type = models.ForeignKey(
        MinutaType, db_column="minuta_type_id", on_delete=models.DO_NOTHING, related_name="themes"
    )
    slug = models.TextField()
    description = models.TextField(blank=True, null=True)
    norm_ids = ArrayField(models.TextField(), default=list, blank=True)
    position = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = "themes"
        unique_together = [("minuta_type", "slug")]
        ordering = ["minuta_type_id", "position"]

    def __str__(self) -> str:
        return self.slug


class RiskMatrix(models.Model):
    class Criticality(models.TextChoices):
        VERMELHO = "vermelho", "vermelho"
        AMARELO = "amarelo", "amarelo"
        VERDE = "verde", "verde"

    id = models.BigAutoField(primary_key=True)
    theme = models.ForeignKey(
        Theme, db_column="theme_id", on_delete=models.DO_NOTHING, related_name="risks"
    )
    risk_id = models.TextField()
    description = models.TextField()
    criticality = models.CharField(max_length=10, choices=Criticality.choices)
    party = models.CharField(max_length=20, default="locatario")
    norms = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "risk_matrix"
        unique_together = [("theme", "risk_id")]
        ordering = ["theme_id", "risk_id"]

    def __str__(self) -> str:
        return f"{self.risk_id} ({self.criticality})"


class Prompt(models.Model):
    class Kind(models.TextChoices):
        REDIGIR_SYSTEM = "redigir_system", "redigir_system"
        TRIAGEM_RISCO = "triagem_risco", "triagem_risco"
        CONFIRMAR_RISCO = "confirmar_risco", "confirmar_risco"
        REGULA_NORMA = "regula_norma", "regula_norma"

    id = models.BigAutoField(primary_key=True)
    minuta_type = models.ForeignKey(
        MinutaType, db_column="minuta_type_id", on_delete=models.DO_NOTHING, related_name="prompts"
    )
    kind = models.CharField(max_length=30, choices=Kind.choices)
    position = models.IntegerField(default=0)
    prompt_text = models.TextField()
    model = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "prompts"
        unique_together = [("minuta_type", "kind", "position")]
        ordering = ["minuta_type_id", "kind", "position"]

    def __str__(self) -> str:
        return f"{self.minuta_type_id}:{self.kind}#{self.position}"


class DomainHistory(models.Model):
    id = models.BigAutoField(primary_key=True)
    table_name = models.TextField()
    row_id = models.BigIntegerField()
    op = models.TextField()
    old_row = models.JSONField(blank=True, null=True)
    new_row = models.JSONField(blank=True, null=True)
    changed_at = models.DateTimeField()
    db_user = models.TextField()

    class Meta:
        managed = False
        db_table = "domain_history"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"#{self.id} {self.op} {self.table_name}.{self.row_id} ({self.db_user})"


class Analysis(models.Model):
    id = models.UUIDField(primary_key=True)
    status = models.TextField()
    filename_alias = models.TextField()
    text_sha256 = models.TextField()
    params = models.JSONField()
    rules_snapshot = models.JSONField()
    rules_hash = models.TextField()
    matrix_version = models.TextField()
    prompt_version = models.TextField()
    domain_history_id = models.BigIntegerField()
    minuta_type = models.TextField(blank=True, null=True)
    report = models.JSONField(blank=True, null=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = "analyses"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{str(self.id)[:8]} {self.status} {self.matrix_version}"


class AnalysisTrail(models.Model):
    id = models.BigAutoField(primary_key=True)
    analysis = models.ForeignKey(
        Analysis, db_column="analysis_id", on_delete=models.DO_NOTHING, related_name="trail"
    )
    seq = models.IntegerField()
    step = models.TextField()
    clause_n = models.IntegerField(blank=True, null=True)
    input_summary = models.JSONField()
    decision = models.JSONField()
    score = models.FloatField(blank=True, null=True)
    cutoff = models.FloatField(blank=True, null=True)
    matrix_version = models.TextField()
    prompt_version = models.TextField()
    cited_norms = ArrayField(models.TextField(), default=list)
    recorded_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "analysis_trail"
        unique_together = [("analysis", "seq")]
        ordering = ["analysis_id", "seq"]

    def __str__(self) -> str:
        return f"{str(self.analysis_id)[:8]} #{self.seq} {self.step}"


class KbDoc(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4)
    title = models.TextField()
    source = models.TextField(default="kb")
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        managed = False
        db_table = "kb_docs"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class KbChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4)
    doc = models.ForeignKey(
        KbDoc, db_column="doc_id", on_delete=models.CASCADE, related_name="chunks"
    )
    content = models.TextField()
    sequence_order = models.IntegerField()
    embedding = VectorField(dimensions=1536, blank=True, null=True)
    embedding_model = models.TextField(blank=True, null=True)
    indexed_at = models.DateTimeField(default=timezone.now, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        managed = False
        db_table = "kb_chunks"
        ordering = ["doc_id", "sequence_order"]

    def __str__(self) -> str:
        return f"{str(self.doc_id)[:8]} #{self.sequence_order}"
