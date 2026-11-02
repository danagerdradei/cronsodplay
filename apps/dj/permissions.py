from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

DJ_GROUP = "DJ"
ADMIN_GROUP = "Administrador"


def is_dj_or_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__in=[DJ_GROUP, ADMIN_GROUP]).exists()
    )


def dj_required(view):
    """Vistas HTML: redirige al login si no es DJ/Admin."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_dj_or_admin(request.user):
            return redirect_to_login(request.get_full_path())
        return view(request, *args, **kwargs)

    return wrapper


def dj_api_required(view):
    """Endpoints JSON: responde 401/403 en vez de redirigir."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "no_autenticado"}, status=401)
        if not is_dj_or_admin(request.user):
            return JsonResponse({"error": "sin_permiso"}, status=403)
        return view(request, *args, **kwargs)

    return wrapper
