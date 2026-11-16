"""Django settings do admin da Leia. Tabelas da Leia sao ``managed=False`` (DDL em src/db/schema.sql).

Variaveis de ambiente:
* ``DATABASE_URL``: postgresql://usuario:senha@host:porta/banco. Em producao, um login PROPRIO
  (ex.: ``django_login``) membro de ``leia_app``: assim ``domain_history.db_user`` distingue o admin
  de outras ferramentas, e o login nao e dono das tabelas de dominio.
* ``DJANGO_SECRET_KEY``: obrigatoria, exceto com ``DJANGO_DEBUG=true`` ou rodando os testes.
* ``DJANGO_ALLOWED_HOSTS``: lista separada por virgula (padrao: so localhost).
* ``DJANGO_DEBUG``: ``true`` so em desenvolvimento.

TLS e backup ficam na M6; ate la o admin roda so na rede do homelab.
"""

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[1]  # src/management/

DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() in ("1", "true", "yes")
_TESTING = sys.argv[1:2] == ["test"]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not (DEBUG or _TESTING):
        raise ImproperlyConfigured("defina DJANGO_SECRET_KEY (ou DJANGO_DEBUG=true em desenvolvimento)")
    SECRET_KEY = "django-insecure-somente-dev-e-testes"

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "src.management.domain",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "src.management.leia_admin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "src.management.leia_admin.wsgi.application"


def _database_from_url() -> dict:
    url = os.environ.get("DATABASE_URL", "postgresql://leia:leia_lab_2026@localhost:5433/leia_lab")
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
    }


DATABASES = {"default": _database_from_url()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
