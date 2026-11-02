from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from apps.venues.models import Venue


def home(request):
    venues = Venue.objects.filter(is_active=True).order_by("name")
    return render(request, "core/home.html", {"venues": venues})


def health(request):
    """Health check para el balanceador (ALB / ECS). Verifica la base de datos."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db_error"}, status=503)
