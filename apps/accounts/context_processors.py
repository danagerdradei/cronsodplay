from django.conf import settings

from apps.control.permissions import is_platform_admin

from .session import current_guest


def guest(request):
    return {
        "current_guest": current_guest(request),
        "GOOGLE_LOGIN_REQUIRED": settings.GOOGLE_LOGIN_REQUIRED,
        "GOOGLE_CLIENT_ID": settings.GOOGLE_CLIENT_ID,
        "is_platform_admin": is_platform_admin(request.user) if hasattr(request, "user") else False,
    }
