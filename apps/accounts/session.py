"""Sesión del asistente (público). Independiente del login de DJ/Admin de Django."""
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.urls import reverse

SESSION_GUEST_KEY = "guest_id"
SESSION_EMAIL_KEY = "guest_email"  # lo usan las vistas de canciones para prellenar y filtrar


def current_guest(request):
    """Asistente con sesión iniciada con Google (o None). Se cachea por petición."""
    if not hasattr(request, "_cached_guest"):
        from apps.songs.models import Guest

        guest_id = request.session.get(SESSION_GUEST_KEY)
        request._cached_guest = Guest.objects.filter(pk=guest_id).first() if guest_id else None
    return request._cached_guest


def login_guest(request, guest):
    request.session.cycle_key()  # evita fijación de sesión
    request.session[SESSION_GUEST_KEY] = guest.pk
    request.session[SESSION_EMAIL_KEY] = guest.email
    request._cached_guest = guest


def logout_guest(request):
    request.session.pop(SESSION_GUEST_KEY, None)
    request.session.pop(SESSION_EMAIL_KEY, None)
    request._cached_guest = None


def login_required_for_guests():
    return settings.GOOGLE_LOGIN_REQUIRED


def is_staff_preview(request):
    """DJ o Admin con sesión, sin sesión de Google: ve las páginas del público en modo vista previa."""
    from apps.dj.permissions import is_dj_or_admin

    return current_guest(request) is None and is_dj_or_admin(request.user)


def guest_required(view=None, *, json=False, allow_staff_preview=False):
    """
    Exige iniciar sesión con Google cuando GOOGLE_LOGIN_REQUIRED está activo.
    Vistas HTML redirigen a /entrar/?next=…; las JSON responden 401.
    Con allow_staff_preview, el DJ/Admin pasa sin Google (la vista decide qué puede hacer).
    """

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if allow_staff_preview and is_staff_preview(request):
                return func(request, *args, **kwargs)
            if login_required_for_guests() and current_guest(request) is None:
                if json:
                    return JsonResponse({"error": "inicia_sesion", "login_url": reverse("accounts:login")}, status=401)
                return redirect_to_login(request.get_full_path(), reverse("accounts:login"))
            return func(request, *args, **kwargs)

        return wrapper

    return decorator(view) if view else decorator
