from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import include, path, reverse

from apps.dj.views import DjLoginView


def admin_login_redirect(request):
    """El login del /admin/ usa el mismo acceso que el DJ."""
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(reverse("staff_login") + (f"?{query}" if query else ""))


admin.site.site_header = "Cronso Dplay · Administración"
admin.site.site_title = "Cronso Dplay"
admin.site.index_title = "Panel de administración"

urlpatterns = [
    path("acceso/", DjLoginView.as_view(), name="staff_login"),  # acceso único DJ + Admin
    path("control/", include("apps.control.urls")),  # panel del Admin de la plataforma
]

# El administrador avanzado de Django solo existe si DJANGO_ADMIN_ENABLED está activo
# (por defecto, solo en local con DEBUG). En producción /admin/ responde 404.
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns += [
        path("admin/login/", admin_login_redirect),
        path("admin/", admin.site.urls),
    ]

urlpatterns += [
    path("", include("apps.events.urls")),  # /e/<código>/ y /dj/eventos/
    path("", include("apps.accounts.urls")),  # /entrar/, /perfil/, /salir/
    path("dj/", include("apps.dj.urls")),
    path("v/", include("apps.venues.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.songs.urls")),
]

# Páginas de error con el diseño de la app (se usan cuando DEBUG=0, es decir, en producción).
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
