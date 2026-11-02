from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render

from apps.dj.permissions import ADMIN_GROUP


def is_platform_admin(user):
    """Admin de la plataforma: superusuario o miembro del grupo Administrador."""
    return user.is_authenticated and user.is_active and (
        user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists()
    )


def admin_required(view):
    """Solo el Admin. Sin sesión → acceso; un DJ ve una página de 'sin permiso'."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_platform_admin(request.user):
            return render(request, "control/forbidden.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper
