import json
import logging

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.songs.models import Guest, SongRequest
from apps.songs.device import get_device_id
from apps.songs.services import AliasTaken, alias_taken, quota_by_event

from .forms import ProfileForm
from .google import GoogleAuthError, verify_credential
from .session import current_guest, guest_required, login_guest, logout_guest

logger = logging.getLogger(__name__)


def _safe_next(request, value, default="songs:request"):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()},
                                                 require_https=request.is_secure()):
        return value
    return reverse(default)


def login_view(request):
    """Página con el botón "Continuar con Google"."""
    next_url = _safe_next(request, request.GET.get("next"))
    if current_guest(request):
        return redirect(next_url)
    return render(request, "accounts/login.html", {"next": next_url})


@transaction.atomic
def guest_from_google(data):
    """
    Busca el perfil por cuenta de Google y, si no, por correo (vincula a quien ya pedía con su
    correo). Si no existe, lo crea con los datos de Google. Nombres ya registrados no se cambian.
    """
    guest = (
        Guest.objects.select_for_update().filter(google_sub=data["sub"]).first()
        or Guest.objects.select_for_update().filter(email=data["email"]).first()
    )
    if guest is None:
        return Guest.objects.create(
            email=data["email"], google_sub=data["sub"], first_name=data["first_name"] or data["email"].split("@")[0],
            last_name=data["last_name"], phone="", picture_url=data["picture"],
        )
    guest.google_sub = guest.google_sub or data["sub"]
    guest.first_name = guest.first_name or data["first_name"]
    guest.last_name = guest.last_name or data["last_name"]
    guest.picture_url = data["picture"] or guest.picture_url
    guest.save()
    return guest


@require_POST
def google_callback(request):
    """Recibe el ID token de Google (vía fetch con CSRF), lo verifica e inicia la sesión."""
    try:
        payload = json.loads(request.body or b"{}")
        data = verify_credential(payload.get("credential", ""))
    except (GoogleAuthError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Inicio de sesión con Google rechazado: %s", exc)
        return JsonResponse({"error": "No pudimos verificar tu cuenta de Google. Intenta de nuevo."}, status=400)
    try:
        guest = guest_from_google(data)
    except IntegrityError:
        return JsonResponse({"error": "Esta cuenta ya está vinculada a otro perfil."}, status=409)
    login_guest(request, guest)
    return JsonResponse({"redirect": _safe_next(request, payload.get("next"))})


@require_POST
def logout_view(request):
    logout_guest(request)
    return redirect("core:home")


@guest_required
def profile(request):
    """Perfil del asistente: datos de Google, alias, celular e historial por evento."""
    guest = current_guest(request)
    if guest is None:  # login no exigido y sin sesión
        return redirect("accounts:login")

    form = ProfileForm(request.POST or None, instance=guest)
    if request.method == "POST" and form.is_valid():
        alias = form.cleaned_data.get("alias", "")
        if alias and not guest.alias and alias_taken(alias, guest.email):
            form.add_error("alias", "Ese alias ya lo está usando otra persona. Elige otro.")
        else:
            try:
                form.save()
            except (IntegrityError, AliasTaken):
                form.add_error("alias", "Ese alias ya lo está usando otra persona. Elige otro.")
            else:
                messages.success(request, "Perfil actualizado.")
                return redirect("accounts:profile")

    open_events = quota_by_event(guest.email, get_device_id(request)[0])
    history = guest.requests.select_related("venue", "event").order_by("-created_at")[:50]
    return render(request, "accounts/profile.html", {
        "guest": guest, "form": form, "open_events": open_events, "history": history,
        "total": guest.requests.count(), "played": guest.requests.filter(status=SongRequest.Status.PLAYED).count(),
    })
