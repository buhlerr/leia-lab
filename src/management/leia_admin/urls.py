from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.generic import RedirectView
from django.views.static import serve as static_serve

from src.management.leia_admin.settings import STATIC_ROOT

admin.site.site_header = "Leia: regras e auditoria"
admin.site.site_title = "Leia admin"

urlpatterns = [
    # O SSO do Pangolin devolve o usuario para a raiz do dominio; sem isso, "/" dava 404.
    path("", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("ping/", lambda _r: JsonResponse({"ok": True})),
    # gunicorn nao serve estaticos.
    path("static/<path:path>", static_serve, {"document_root": str(STATIC_ROOT)}),
]
