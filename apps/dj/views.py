import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django import forms
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.events.models import Event
from apps.songs.api import with_ratings
from apps.songs.models import Guest, LimitReset, SongRequest
from apps.songs.services import _since, limits_for, reset_limit
from apps.venues.models import Venue

from .permissions import dj_api_required, dj_required, is_dj_or_admin
from .serializers import mask_email, serialize_request

MAX_RESULTS = 300


class StaffAuthenticationForm(AuthenticationForm):
    """Solo entran usuarios con perfil DJ o Admin (evita un bucle de redirecciones con usuarios sin rol)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuario o contraseña incorrectos.",
        "no_role": "Tu usuario no tiene perfil de DJ ni de Admin. Pídele acceso al administrador.",
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not (user.is_staff or is_dj_or_admin(user)):
            raise forms.ValidationError(self.error_messages["no_role"], code="no_role")


class DjLoginView(auth_views.LoginView):
    """Acceso único para DJ y Admin (también reemplaza el login del /admin/)."""

    template_name = "dj/login.html"
    authentication_form = StaffAuthenticationForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # Sin ?next=: el Admin va a su panel de control y el DJ a la cola.
        from apps.control.permissions import is_platform_admin

        return reverse("control:dashboard") if is_platform_admin(self.request.user) else reverse("dj:panel")

    # El modal "Acceso DJ" envía el formulario con fetch: responde JSON para mostrar el error ahí mismo.
    def _is_ajax(self):
        return self.request.headers.get("x-requested-with") == "XMLHttpRequest"

    def form_valid(self, form):
        response = super().form_valid(form)
        if self._is_ajax():
            return JsonResponse({"redirect": response.url})
        return response

    def form_invalid(self, form):
        if self._is_ajax():
            errors = form.non_field_errors() or ["Escribe tu usuario y tu contraseña."]
            return JsonResponse({"error": " ".join(errors)}, status=400)
        return super().form_invalid(form)


@dj_required
def panel(request):
    venues = Venue.objects.filter(is_active=True)
    events = Event.objects.filter(is_open=True).select_related("venue")
    return render(
        request,
        "dj/panel.html",
        {
            "venues": venues, "events": events, "poll_seconds": settings.DJ_PANEL_POLL_SECONDS,
            "statuses": SongRequest.Status.choices, "dj_tab": "queue",
        },
    )


@require_GET
@dj_api_required
def api_requests(request):
    """
    Lista de solicitudes en orden de llegada (prioridad).
    Filtros: ?venue=<slug>&status=pending|played|rejected|all
    """
    qs = SongRequest.objects.select_related("guest", "venue", "event")
    venue_slug = request.GET.get("venue")
    if venue_slug:
        qs = qs.filter(venue__slug=venue_slug)
    event_code = request.GET.get("event")
    if event_code:
        qs = qs.filter(event__code=event_code.upper())

    counts = qs.aggregate(
        pending=Count("id", filter=Q(status=SongRequest.Status.PENDING)),
        played=Count("id", filter=Q(status=SongRequest.Status.PLAYED)),
        rejected=Count("id", filter=Q(status=SongRequest.Status.REJECTED)),
    )

    status = request.GET.get("status", SongRequest.Status.PENDING)
    if status != "all":
        if status not in SongRequest.Status.values:
            return JsonResponse({"error": "estado_invalido"}, status=400)
        qs = qs.filter(status=status)

    # Pendientes: la más antigua primero (prioridad). Resto: lo más reciente primero.
    qs = with_ratings(qs).order_by("created_at" if status == SongRequest.Status.PENDING else "-created_at")
    qs = qs[:MAX_RESULTS]
    results = [serialize_request(s, position=i) for i, s in enumerate(qs, start=1)]
    return JsonResponse({"server_time": timezone.now().isoformat(), "counts": counts, "results": results})


@require_POST
@dj_api_required
def api_update_status(request, pk):
    """Cambia el estado de una solicitud. Body JSON: {"status": "played"}."""
    try:
        new_status = json.loads(request.body or b"{}").get("status")
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "json_invalido"}, status=400)
    if new_status not in SongRequest.Status.values:
        return JsonResponse({"error": "estado_invalido"}, status=400)

    song = get_object_or_404(SongRequest.objects.select_related("guest", "venue"), pk=pk)
    song.status = new_status
    song.status_changed_at = timezone.now()
    song.handled_by = request.user
    song.save(update_fields=["status", "status_changed_at", "handled_by"])
    return JsonResponse(serialize_request(song))


def _limit_scope_from(request):
    """Alcance elegido en la página de límites: un evento abierto o 'sin evento'."""
    open_events = list(Event.objects.filter(is_open=True).select_related("venue"))
    code = request.GET.get("evento", request.POST.get("evento"))
    if code is None:  # por defecto, el evento abierto más reciente
        return (open_events[0] if open_events else None), open_events
    if code == "":
        return None, open_events
    event = Event.objects.select_related("venue").filter(code=code.upper()).first()
    return event, open_events


@dj_required
def limits(request):
    """Buscar personas por correo, nombre o alias y restablecer su cupo de canciones."""
    event, open_events = _limit_scope_from(request)
    per_person, _ = limits_for(event)
    scope = Q(requests__counts_toward_limit=True)
    if event:
        scope &= Q(requests__event=event)
    else:
        scope &= Q(requests__event__isnull=True)
        start = _since(settings.SONG_LIMIT_WINDOW_HOURS)
        if start:
            scope &= Q(requests__created_at__gte=start)

    guests = Guest.objects.annotate(used=Count("requests", filter=scope), last=Max("requests__created_at"))
    query = request.GET.get("q", "").strip()
    if query:
        guests = guests.filter(
            Q(email__icontains=query) | Q(first_name__icontains=query)
            | Q(last_name__icontains=query) | Q(alias__icontains=query)
        )
    else:
        guests = guests.filter(used__gte=per_person)  # sin búsqueda: quienes ya llegaron al límite
    guests = guests.order_by("-last")[:50]

    rows = [
        {
            "guest": g,
            "masked_email": mask_email(g.email),
            "used": g.used,
            "remaining": max(per_person - g.used, 0),
            "at_limit": g.used >= per_person,
        }
        for g in guests
    ]
    resets = LimitReset.objects.select_related("guest", "reset_by", "event")[:10]
    return render(request, "dj/limits.html", {
        "rows": rows, "query": query, "event": event, "open_events": open_events,
        "per_person": per_person, "resets": resets, "dj_tab": "limits",
    })


@require_POST
@dj_required
def reset_guest_limit(request, guest_id):
    guest = get_object_or_404(Guest, pk=guest_id)
    code = request.POST.get("evento", "")
    event = Event.objects.filter(code=code.upper()).first() if code else None
    released = reset_limit(guest, request.user, event)
    messages.success(
        request,
        f"Listo: {guest.display_name} puede volver a pedir canciones "
        f"({released} pedido{'s' if released != 1 else ''} liberado{'s' if released != 1 else ''}).",
    )
    params = {"evento": code}
    if request.POST.get("q"):
        params["q"] = request.POST["q"]
    return redirect(f"{reverse('dj:limits')}?{urlencode(params)}")



@require_POST
@dj_api_required
def api_delete_request(request, pk):
    """Elimina una canción de la cola. DJ: solo de sus eventos (o sin evento). Admin: cualquiera."""
    from apps.control.permissions import is_platform_admin

    song = get_object_or_404(SongRequest.objects.select_related("event"), pk=pk)
    if not is_platform_admin(request.user) and song.event_id and song.event.dj_id != request.user.pk:
        return JsonResponse({"error": "sin_permiso"}, status=403)
    song.delete()  # la persona recupera ese cupo
    return JsonResponse({"deleted": pk})
