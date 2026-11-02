import io

import segno
from django.conf import settings
from django.contrib import messages
from django.db.models import Avg, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from apps.control.permissions import is_platform_admin
from apps.dj.permissions import dj_required
from apps.songs.models import ExperienceRating
from apps.songs.views import request_song

from .forms import EventForm
from .models import Event


def _get_event(code):
    return get_object_or_404(Event.objects.select_related("venue", "dj"), code=code.upper())


def _get_dj_event(request, code):
    """El DJ solo gestiona sus propios eventos; el Admin, todos."""
    qs = Event.objects.select_related("venue", "dj")
    if not is_platform_admin(request.user):
        qs = qs.filter(dj=request.user)
    return get_object_or_404(qs, code=code.upper())


# --- Público ---------------------------------------------------------------

def entry(request, code):
    """Destino del link/QR del evento: el formulario con la discoteca y el cupo del evento."""
    event = _get_event(code)
    if not event.is_open or not event.venue.is_active:
        return render(request, "events/closed.html", {"event": event}, status=410)
    return request_song(request, event=event)


@cache_control(max_age=3600)
def qr(request, code):
    """QR del evento. ?formato=png para descargar/compartir por WhatsApp; SVG por defecto (impresión)."""
    event = _get_event(code)
    code_img = segno.make(event.public_url, error="h")
    if request.GET.get("formato") == "png":
        buffer = io.BytesIO()
        code_img.save(buffer, kind="png", scale=12, border=3, dark="#000000", light="#ffffff")
        response = HttpResponse(buffer.getvalue(), content_type="image/png")
    else:
        # save(kind="svg") incluye xmlns: necesario para que el SVG funcione dentro de <img>.
        buffer = io.BytesIO()
        code_img.save(buffer, kind="svg", scale=10, border=2, dark="#000000", light="#ffffff", xmldecl=False)
        response = HttpResponse(buffer.getvalue(), content_type="image/svg+xml")
    if request.GET.get("descargar"):
        ext = "png" if request.GET.get("formato") == "png" else "svg"
        response["Content-Disposition"] = f'attachment; filename="qr-{event.code}.{ext}"'
    return response


# --- DJ --------------------------------------------------------------------

@dj_required
def dj_list(request):
    """Vista del DJ: sus eventos + crear uno nuevo. El Admin usa su propia vista en /control/eventos/."""
    if is_platform_admin(request.user):
        return redirect("control:events")
    form = EventForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.dj = request.user
        event.save()
        messages.success(request, f"Evento «{event.name}» creado. Ya puedes compartir su link y QR.")
        return redirect("events:dj_detail", code=event.code)

    events = Event.objects.filter(dj=request.user).select_related("venue", "dj").annotate(
        total=Count("requests", distinct=True), people=Count("requests__guest", distinct=True),
        rating=Avg("experience_ratings__event_stars"), rating_n=Count("experience_ratings__event_stars", distinct=True),
    )
    my_rating = ExperienceRating.objects.filter(dj=request.user, dj_stars__isnull=False).aggregate(
        avg=Avg("dj_stars"), n=Count("id"))
    return render(request, "events/dj_list.html",
                  {"form": form, "events": events, "my_rating": my_rating, "dj_tab": "events"})


@dj_required
def dj_detail(request, code):
    event = _get_dj_event(request, code)
    stats = event.requests.aggregate(total=Count("id"), people=Count("guest", distinct=True))
    return render(request, "events/dj_detail.html", {"event": event, "stats": stats, "dj_tab": "events"})


@require_POST
@dj_required
def dj_toggle(request, code):
    event = _get_dj_event(request, code)
    event.is_open = not event.is_open
    event.closed_at = None if event.is_open else timezone.now()
    event.save(update_fields=["is_open", "closed_at"])
    messages.success(request, f"Evento {'reabierto' if event.is_open else 'cerrado'}.")
    return redirect("events:dj_detail", code=event.code)


@dj_required
def dj_playlist(request, code):
    """Playlist de un evento: la cola en vivo solo de ese evento (DJ dueño o Admin)."""
    event = _get_dj_event(request, code)
    rating = event.experience_ratings.aggregate(
        event_avg=Avg("event_stars"), event_n=Count("event_stars"), dj_avg=Avg("dj_stars"), dj_n=Count("dj_stars"))
    return render(request, "dj/panel.html", {
        "fixed_event": event, "rating": rating, "poll_seconds": settings.DJ_PANEL_POLL_SECONDS,
        "dj_tab": "events",
    })


@dj_required
def dj_print(request, code):
    return render(request, "events/print.html", {"event": _get_dj_event(request, code)})
