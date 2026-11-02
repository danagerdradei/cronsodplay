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
    path("admin/login/", admin_login_redirect),
    path("control/", include("apps.control.urls")),  # panel del Admin de la plataforma
    path("admin/", admin.site.urls),
    path("", include("apps.events.urls")),  # /e/<código>/ y /dj/eventos/
    path("", include("apps.accounts.urls")),  # /entrar/, /perfil/, /salir/
    path("dj/", include("apps.dj.urls")),
    path("v/", include("apps.venues.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.songs.urls")),
]
