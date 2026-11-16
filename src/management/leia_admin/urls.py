from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.static import serve as static_serve

from src.management.leia_admin.settings import STATIC_ROOT

admin.site.site_header = "Leia: regras e auditoria"
admin.site.site_title = "Leia admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ping/", lambda _r: JsonResponse({"ok": True})),
    # gunicorn nao serve estaticos; volume baixo (uso interno) dispensa um servidor so para isso.
    path("static/<path:path>", static_serve, {"document_root": str(STATIC_ROOT)}),
]
