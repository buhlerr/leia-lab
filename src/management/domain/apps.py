from django.apps import AppConfig


class DomainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "src.management.domain"
    label = "domain"
    verbose_name = "LEIA — regras e auditoria"
