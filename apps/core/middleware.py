from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """
    Responde /health/ antes que cualquier otro middleware.

    Los balanceadores (Render, ALB) llaman por HTTP interno y con un Host propio: si pasara por
    SecurityMiddleware/ALLOWED_HOSTS recibirían una redirección a HTTPS o un 400 y darían el
    servicio por caído.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health/":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return JsonResponse({"status": "ok"})
            except Exception:  # noqa: BLE001
                return JsonResponse({"status": "db_error"}, status=503)
        return self.get_response(request)
