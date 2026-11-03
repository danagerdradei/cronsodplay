import csv
import io

import segno
from django.conf import settings
from django.contrib import messages
from django.db.models import Avg, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from apps.control.permissions import is_platform_admin
from apps.dj.permissions import dj_required
from apps.songs.models import ExperienceRating
from apps.songs.views import request_song

from .forms import EventForm
from .models import Event
from .services import finalize_event


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
    if not event.is_open or event.is_finalized or not event.venue.is_active:
        return render(request, "events/closed.html", {"event": event}, status=410)
    if not event.accepting_requests:
        # Pausado por el DJ: no se reciben pedidos, pero la cola se sigue viendo.
        return render(request, "events/paused.html", {"event": event, "venue": event.venue})
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

    events = Event.objects.filter(dj=request.user, finalized_at__isnull=True).select_related("venue", "dj").annotate(
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
    if event.is_finalized:
        messages.error(request, "Este evento ya fue finalizado: su playlist está en el historial.")
        return redirect("events:dj_history_detail", code=event.code)
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



@require_POST
@dj_required
def dj_pause(request, code):
    """Pausar o reanudar la recepción de pedidos (el link y el QR siguen activos)."""
    event = _get_dj_event(request, code)
    if event.is_finalized or not event.is_open:
        messages.error(request, "El evento no está abierto.")
    else:
        event.accepting_requests = not event.accepting_requests
        event.save(update_fields=["accepting_requests"])
        messages.success(request, "▶️ Pedidos reanudados." if event.accepting_requests
                         else "⏸️ Pedidos pausados: el público ve un aviso y la cola sigue visible.")
    back = request.POST.get("volver", "")
    if back and url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        return redirect(back)
    return redirect("events:dj_detail", code=event.code)


@require_POST
@dj_required
def dj_finalize(request, code):
    """Cierra el evento para siempre y guarda su playlist en el historial."""
    event = _get_dj_event(request, code)
    if request.POST.get("confirmar", "").strip().upper() != event.code:
        messages.error(request, f"Para finalizar «{event.name}» escribe su código: {event.code}.")
        return redirect("events:dj_detail", code=event.code)
    finalize_event(event, request.user)
    total = event.playlist_snapshot.get("summary", {}).get("total", 0)
    messages.success(request, f"🏁 Evento «{event.name}» finalizado. Su playlist ({total} canciones) quedó en el historial.")
    return redirect("events:dj_history_detail", code=event.code)


def _history_queryset(request):
    qs = Event.objects.filter(finalized_at__isnull=False).select_related("venue", "dj", "finalized_by")
    return qs if is_platform_admin(request.user) else qs.filter(dj=request.user)


@dj_required
def dj_history(request):
    events = _history_queryset(request).order_by("-finalized_at")
    return render(request, "events/history_list.html", {"events": events, "dj_tab": "history"})


@dj_required
def dj_history_detail(request, code):
    event = get_object_or_404(_history_queryset(request), code=code.upper())
    snap = event.playlist_snapshot or {}
    return render(request, "events/history_detail.html", {
        "event": event, "songs": snap.get("songs", []), "summary": snap.get("summary", {}), "dj_tab": "history",
    })


@dj_required
def dj_history_csv(request, code):
    event = get_object_or_404(_history_queryset(request), code=code.upper())
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="playlist-{event.code}.csv"'
    response.write("\ufeff")  # BOM para que Excel abra bien las tildes
    writer = csv.writer(response)
    writer.writerow(["#", "Canción", "Artista", "Género", "Estado", "Pedida por", "Correo", "Link", "Video",
                     "Estrellas", "Votos", "Fecha"])
    for s in (event.playlist_snapshot or {}).get("songs", []):
        writer.writerow([s["position"], s["title"], s["artist"], s["genre"], s["status_label"], s["requester"],
                         s["requester_email"], s["link"], s["video_title"], s["rating_avg"] or "", s["rating_n"],
                         s["requested_at"][:16].replace("T", " ")])
    return response
