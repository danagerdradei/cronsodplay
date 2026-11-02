"""
Verificación del "Sign in with Google" (Google Identity Services).

El navegador recibe de Google un ID token (JWT firmado) y nos lo envía. Aquí se verifica
la firma con los certificados públicos de Google, que el token sea para NUESTRO client ID,
que no haya expirado y que el correo esté verificado. No se necesita client secret.
"""
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

_transport = google_requests.Request()  # reutiliza conexiones y cachea los certificados de Google


class GoogleAuthError(Exception):
    pass


def verify_credential(credential):
    """Devuelve los datos del usuario de Google o lanza GoogleAuthError."""
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleAuthError("GOOGLE_CLIENT_ID no está configurado")
    try:
        claims = id_token.verify_oauth2_token(credential, _transport, settings.GOOGLE_CLIENT_ID)
    except ValueError as exc:  # firma inválida, expirado, audiencia incorrecta…
        raise GoogleAuthError(str(exc)) from exc
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("Emisor inválido")
    if not claims.get("email") or not claims.get("email_verified"):
        raise GoogleAuthError("La cuenta de Google no tiene un correo verificado")
    return {
        "sub": claims["sub"],
        "email": claims["email"].strip().lower(),
        "first_name": (claims.get("given_name") or claims.get("name") or "").strip()[:80],
        "last_name": (claims.get("family_name") or "").strip()[:80],
        "picture": claims.get("picture", "")[:500],
    }
