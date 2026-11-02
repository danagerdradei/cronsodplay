from django.db import connection
from django.http import HttpResponseServerError, JsonResponse
from django.shortcuts import render
from django.template import loader

from apps.venues.models import Venue


def home(request):
    venues = Venue.objects.filter(is_active=True).order_by("name")
    return render(request, "core/home.html", {"venues": venues})


def page_not_found(request, exception=None):
    """404 con el diseño de la app. En /admin/ (apagado en producción) explica que el acceso está restringido."""
    restricted = request.path.startswith("/admin")
    return render(request, "404.html", {"restricted": restricted}, status=404)


def server_error(request):
    """500 sin consultas a la BD ni procesadores de contexto: debe funcionar aunque la BD esté caída."""
    return HttpResponseServerError(loader.get_template("500.html").render())


def health(request):
    """Health check para el balanceador (ALB / ECS). Verifica la base de datos."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db_error"}, status=503)
