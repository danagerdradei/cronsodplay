from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from django.contrib import messages

from apps.accounts.session import current_guest, guest_required, is_staff_preview, logout_guest
from apps.core.net import get_client_ip
from apps.venues.models import Venue

from .device import get_device_id, set_device_cookie
from .forms import EmailLookupForm, SongRequestForm
from .models import Guest, SongRequest
from .services import (
    AliasTaken,
    DuplicateSong,
    SongAlreadyInEvent,
    ExperienceRequired,
    GenreNotAllowed,
    LinkAlreadyUsed,
    IdentityMismatch,
    LimitReached,
    limits_for,
    register_song_request,
    remaining,
    remaining_for_device,
    remaining_for_email,
    experience_targets,
    needs_experience,
)

SESSION_EMAIL_KEY = "guest_email"


def _initial_from_session(request):
    """Prellena los datos de la persona si ya pidió antes desde este dispositivo."""
    email = request.session.get(SESSION_EMAIL_KEY)
    guest = Guest.objects.filter(email=email).first() if email else None
    if not guest:
        return {}, None
    initial = {f: getattr(guest, f) for f in SongRequestForm.GUEST_FIELDS}
    return initial, guest


def _quota(event=None):
    per_person, _ = limits_for(event)
    return {"max_songs": per_person, "quota_slots": range(1, per_person + 1)}


def _limit_page(request, email, reason, device_id, venue=None, event=None):
    # Solo el límite por correo se explica; dispositivo/IP muestran un mensaje genérico.
    # "Usar otro correo" solo se ofrece si al dispositivo aún le queda cupo.
    can_switch = reason == "email" and remaining_for_device(device_id, event) != 0
    return render(
        request,
        "songs/limit_reached.html",
        {
            "email": email, "reason": reason, "can_switch_email": can_switch,
            "venue": venue, "event": event, **_quota(event),
        },
    )


@require_http_methods(["GET", "POST"])
@guest_required(allow_staff_preview=True)
def request_song(request, venue_slug=None, event=None):
    """Formulario de pedido. Con `event` (link/QR del evento) la discoteca y el cupo salen del evento."""
    if event is not None:
        venue = event.venue
    else:
        venue = get_object_or_404(Venue, slug=venue_slug, is_active=True) if venue_slug else None
        if settings.REQUESTS_REQUIRE_EVENT:
            return choose_event(request, venue)
    device_id, new_device = get_device_id(request)
    response = _request_song(request, venue, device_id, event)
    if new_device:
        set_device_cookie(response, device_id)
    return response


def choose_event(request, venue=None):
    """
    Sin evento no se piden canciones: se muestran los eventos abiertos (de esa discoteca, si viene
    del QR del local). Si la discoteca tiene un solo evento abierto, se entra directo.
    """
    from apps.events.models import Event

    events = Event.objects.filter(is_open=True, finalized_at__isnull=True, venue__is_active=True)
    if venue is not None:
        events = events.filter(venue=venue)
    events = list(events.select_related("venue").order_by("venue__name", "-created_at"))
    if venue is not None and len(events) == 1:
        return redirect(events[0].get_absolute_url())
    groups = {}
    for e in events:
        groups.setdefault(e.venue_id, {"venue": e.venue, "events": []})["events"].append(e)
    return render(request, "songs/choose_event.html", {"groups": list(groups.values()), "venue": venue})


def _request_song(request, venue, device_id, event=None):
    google_guest = current_guest(request)
    staff_preview = is_staff_preview(request)
    if staff_preview and request.method == "POST":
        # El DJ/Admin solo mira: los pedidos los hace el público con su cuenta de Google.
        messages.info(request, "Estás en la vista de público: los pedidos los hace el público con su cuenta.")
        return redirect(request.get_full_path())
    initial, known_guest = _initial_from_session(request)
    if google_guest is not None:
        known_guest = google_guest
        initial = {"alias": google_guest.alias, "phone": google_guest.phone}
    if venue:
        initial["venue"] = venue.pk
    else:
        active = list(Venue.objects.filter(is_active=True).values_list("pk", flat=True)[:2])
        if len(active) == 1:  # una sola discoteca: no hace falta elegir
            initial["venue"] = active[0]

    ask_experience = False
    if request.method == "POST":
        form = SongRequestForm(request.POST, initial=initial, event=event, guest=google_guest)
        if known_guest:
            form.lock_identity(known_guest)
        if form.is_valid():
            email = form.guest_data()["email"]
            try:
                song = register_song_request(
                    guest_data=form.guest_data(),
                    song_data=form.song_data(),
                    client_ip=get_client_ip(request),
                    device_id=device_id,
                    event=event,
                    experience=form.experience_data(),
                )
            except LimitReached as exc:
                request.session[SESSION_EMAIL_KEY] = email
                return _limit_page(request, email, exc.reason, device_id, venue, event)
            except SongAlreadyInEvent as exc:
                if exc.status == SongRequest.Status.PLAYED:
                    msg = "Esa canción ya sonó esta noche. ¡Pide otra!"
                elif exc.status == SongRequest.Status.REJECTED:
                    msg = "Esa canción ya la pidieron y el DJ no la tiene disponible. ¡Pide otra!"
                else:
                    msg = "Esa canción ya está en la cola de esta noche: no hace falta pedirla de nuevo. "                           "Puedes puntuarla en la playlist y pedir otra."
                form.add_error("title", msg)
            except DuplicateSong:
                form.add_error("title", "Ya pediste esta canción con este correo. ¡Prueba con otra!")
            except IdentityMismatch as exc:
                # No se revela cuáles eran los datos registrados (evita averiguar datos de un correo ajeno).
                for field in exc.fields:
                    form.add_error(field, "No coincide con lo que registraste la primera vez con este correo.")
                form.add_error(None, "Este correo ya está registrado. Escribe tus nombres, apellidos y alias "
                                     "tal como los pusiste la primera vez.")
            except ExperienceRequired as exc:
                ask_experience = True
                for field in exc.fields:
                    form.add_error(field, "Elige de 1 a 5 estrellas.")
                form.add_error(None, "Es tu última canción de la noche: califica tu experiencia para enviarla.")
            except LinkAlreadyUsed:
                form.add_error("reference_url", "Ya usaste este mismo link para otra canción. "
                                                "Pega el link de la canción que estás pidiendo.")
            except GenreNotAllowed:
                form.add_error("genre", form.fields["genre"].error_messages["invalid_choice"])
            except AliasTaken:
                form.add_error("alias", "Ese alias ya lo está usando otra persona. Elige otro o déjalo en blanco.")
            else:
                request.session[SESSION_EMAIL_KEY] = email
                return redirect("songs:success", pk=song.pk)
    else:
        form = SongRequestForm(initial=initial, event=event, guest=google_guest)
        if known_guest:
            form.lock_identity(known_guest)

    left = remaining(known_guest.email if known_guest else None, device_id, event)
    if request.method == "GET" and left == 0 and not staff_preview:
        email_left = remaining_for_email(known_guest.email, event) if known_guest else 1
        reason = "email" if email_left == 0 else "device"
        return _limit_page(request, known_guest.email if known_guest else "", reason, device_id, venue, event)

    # ¿Mostrar la calificación de la noche? (última canción del cupo de una persona conocida,
    # o si ya se pidió/llenó en este envío)
    target_venue = event.venue if event else venue
    if target_venue is None and initial.get("venue"):
        target_venue = Venue.objects.filter(pk=initial["venue"]).first()
    if request.method == "POST" and any(request.POST.get(f) for f in ("venue_stars", "event_stars", "dj_stars")):
        ask_experience = True
    if not ask_experience and target_venue is not None:
        ask_experience = needs_experience(known_guest, event, target_venue) if known_guest else (
            limits_for(event)[0] == 1)
    experience = experience_targets(event, target_venue) if ask_experience and target_venue else None

    return render(
        request,
        "songs/request_form.html",
        {"form": form, "venue": venue, "event": event, "known_guest": known_guest, "remaining": left,
         "experience": experience, "staff_preview": staff_preview, **_quota(event)},
    )


@guest_required
def success(request, pk):
    email = request.session.get(SESSION_EMAIL_KEY)
    # Solo quien hizo la solicitud (misma sesión) puede ver esta página.
    song = get_object_or_404(
        SongRequest.objects.select_related("guest", "venue", "event"), pk=pk, guest__email=email
    )
    position = SongRequest.objects.filter(
        venue=song.venue, event=song.event, status=SongRequest.Status.PENDING, created_at__lte=song.created_at
    ).count()
    device_id, _ = get_device_id(request)
    event = song.event if song.event and song.event.is_open else None
    return render(
        request,
        "songs/success.html",
        {"song": song, "event": event, "remaining": remaining(email, device_id, song.event),
         "position": position, **_quota(song.event)},
    )


@require_http_methods(["GET", "POST"])
@guest_required
def my_requests(request):
    """La persona ve SOLO las canciones pedidas con su correo (o con su cuenta de Google)."""
    if current_guest(request) is not None:
        request.session[SESSION_EMAIL_KEY] = current_guest(request).email
    if request.method == "POST" and current_guest(request) is None:
        form = EmailLookupForm(request.POST)
        if form.is_valid():
            request.session[SESSION_EMAIL_KEY] = form.cleaned_data["email"]
            return redirect("songs:my_requests")
    else:
        form = EmailLookupForm(initial={"email": request.session.get(SESSION_EMAIL_KEY, "")})

    email = request.session.get(SESSION_EMAIL_KEY)
    songs = (
        SongRequest.objects.filter(guest__email=email).select_related("venue").order_by("-created_at")
        if email
        else SongRequest.objects.none()
    )
    return render(
        request,
        "songs/my_requests.html",
        {
            "form": form,
            "email": email,
            "songs": songs,
            "remaining": remaining(email, get_device_id(request)[0]) if email else None,
        },
    )


@require_http_methods(["POST"])
def forget_me(request):
    """Cierra la 'sesión' del asistente en este dispositivo (útil en celulares prestados)."""
    logout_guest(request)  # también cierra la sesión de Google si la había
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("songs:my_requests")
