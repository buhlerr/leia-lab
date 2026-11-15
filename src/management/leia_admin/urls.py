from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.static import serve as static_serve

from src.management.leia_admin.settings import STATIC_ROOT

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ping/", lambda _r: JsonResponse({"ok": True, "tool": "django-admin"})),
    path("static/<path:path>", static_serve, {"document_root": str(STATIC_ROOT)}),
]
