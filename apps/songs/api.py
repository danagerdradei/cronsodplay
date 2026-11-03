"""
API pública (sin login) para la cola en vivo que ve el público y las puntuaciones con estrellas.

El público nunca recibe correo, celular, apellidos, IP ni dispositivo de nadie.
"""
import hashlib
import json
from urllib.parse import urlparse

from django.core.cache import cache
from django.db.models import Avg, Count, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.session import guest_required
from apps.core.net import get_client_ip
from apps.events.models import Event
from apps.venues.models import Venue

from .device import get_device_id, set_device_cookie
from .forms import ALLOWED_LINK_HOSTS
from .models import SongRating, SongRequest
from .thumbnails import link_matches_song
from .thumbnails import link_preview as link_preview_data

MAX_PENDING = 50
PREVIEW_CACHE_SECONDS = 600
MAX_PLAYED = 5


def with_ratings(qs, device_id=None):
    """Anota promedio y número de votos (y el voto de este dispositivo, si se da)."""
    qs = qs.annotate(rating_avg=Avg("ratings__stars"), rating_count=Count("ratings"))
    if device_id:
        mine = SongRating.objects.filter(song=OuterRef("pk"), device_id=device_id).values("stars")[:1]
        qs = qs.annotate(my_rating=Subquery(mine))
    return qs


def rating_summary(song):
    avg = getattr(song, "rating_avg", None)
    return {
        "avg": round(avg, 1) if avg is not None else None,
        "count": getattr(song, "rating_count", 0),
        "mine": getattr(song, "my_rating", None),
    }


def public_link(song):
    """Link para el público: el que pegó la persona o el video de YouTube encontrado."""
    if song.reference_url:
        return song.reference_url, song.platform or "link"
    video_id = (song.youtube_data or {}).get("video_id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}", "youtube"
    return "", ""


def serialize_public(song, position=None):
    link, platform = public_link(song)
    return {
        "id": song.pk,
        "position": position,
        "link": link,
        "platform": platform,
        "venue": song.venue.name,
        "title": song.title,
        "artist": song.artist,
        "genre_label": song.get_genre_display(),
        "thumbnail_url": song.thumbnail_url,
        "requester": song.guest.public_name,
        "status": song.status,
        "rating": rating_summary(song),
    }


def _find_venue(value):
    qs = Venue.objects.filter(is_active=True)
    return qs.filter(pk=int(value)).first() if str(value).isdigit() else qs.filter(slug=value).first()


@never_cache
@require_GET
def public_queue(request):
    """
    GET /cola/?venue=<slug o id> → canciones en cola (en orden) y las últimas que sonaron.
    Sin `venue` devuelve la cola de todas las discotecas activas.
    """
    event = None
    code = request.GET.get("event", "").strip().upper()
    if code:
        event = Event.objects.select_related("venue").filter(code=code).first()
        if not event:
            return JsonResponse({"error": "evento_no_encontrado"}, status=404)
        venue = event.venue
    else:
        value = request.GET.get("venue", "")
        venue = _find_venue(value) if value else None
        if value and not venue:
            return JsonResponse({"error": "discoteca_no_encontrada"}, status=404)

    device_id, _ = get_device_id(request)
    if event:
        qs = SongRequest.objects.filter(event=event)
    elif venue:
        qs = SongRequest.objects.filter(venue=venue)
    else:
        qs = SongRequest.objects.filter(venue__is_active=True)
    base = with_ratings(qs.select_related("guest", "venue"), device_id)
    pending = list(base.filter(status=SongRequest.Status.PENDING).order_by("created_at")[:MAX_PENDING])
    played = base.filter(status=SongRequest.Status.PLAYED).order_by("-status_changed_at")[:MAX_PLAYED]
    return JsonResponse({
        "venue": {"slug": venue.slug, "name": venue.name} if venue else None,
        "event": {"code": event.code, "name": event.name} if event else None,
        "pending": [serialize_public(s, i) for i, s in enumerate(pending, start=1)],
        "played": [serialize_public(s) for s in played],
    })


@require_POST
@guest_required(json=True)
def rate_song(request, pk):
    """POST /cola/<id>/calificar/ con {"stars": 1-5}. Un voto por dispositivo; se puede cambiar."""
    try:
        stars = int(json.loads(request.body or b"{}").get("stars"))
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "estrellas_invalidas"}, status=400)
    if not 1 <= stars <= 5:
        return JsonResponse({"error": "estrellas_invalidas"}, status=400)

    song = get_object_or_404(
        SongRequest, pk=pk, venue__is_active=True,
        status__in=[SongRequest.Status.PENDING, SongRequest.Status.PLAYED],
    )
    device_id, new_device = get_device_id(request)
    SongRating.objects.update_or_create(
        song=song, device_id=device_id, defaults={"stars": stars, "client_ip": get_client_ip(request)}
    )
    song = with_ratings(SongRequest.objects.filter(pk=song.pk), device_id).get()
    response = JsonResponse({"id": song.pk, "rating": rating_summary(song)})
    if new_device:
        set_device_cookie(response, device_id)
    return response


@require_GET
def link_preview(request):
    """
    GET /link-preview/?url=<link>&title=<canción>&artist=<artista>
    Muestra qué video/track es el link pegado y si parece corresponder a la canción escrita.
    """
    url = request.GET.get("url", "").strip()[:500]
    host = (urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not any(host == h or host.endswith("." + h) for h in ALLOWED_LINK_HOSTS):
        return JsonResponse({"error": "link_invalido"}, status=400)
    key = "link-preview:" + hashlib.sha256(url.encode()).hexdigest()
    data = cache.get(key)
    if data is None:
        data = link_preview_data(url) or {}
        cache.set(key, data, PREVIEW_CACHE_SECONDS)
    if not data:
        return JsonResponse({"error": "no_disponible"}, status=404)
    title, artist = request.GET.get("title", ""), request.GET.get("artist", "")
    return JsonResponse({**data, "matches": link_matches_song(f"{data['title']} {data['author']}", title, artist)})
