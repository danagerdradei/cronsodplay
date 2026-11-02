"""
Identificador anónimo del dispositivo (cookie firmada).

Permite limitar los pedidos por celular/PC aunque la persona cambie de correo.
No contiene datos personales: es un UUID aleatorio.
"""
import uuid

from django.conf import settings
from django.core.signing import BadSignature

COOKIE_NAME = "dplay_device"
COOKIE_SALT = "cronso.device"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 2  # 2 años


def get_device_id(request):
    """Devuelve (device_id, es_nuevo)."""
    try:
        value = request.get_signed_cookie(COOKIE_NAME, salt=COOKIE_SALT)
        uuid.UUID(value)
        return value, False
    except (KeyError, BadSignature, ValueError):
        return uuid.uuid4().hex, True


def set_device_cookie(response, device_id):
    response.set_signed_cookie(
        COOKIE_NAME,
        device_id,
        salt=COOKIE_SALT,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
    )
    return response
