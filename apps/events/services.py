"""Finalizar un evento y guardar su playlist en el historial (copia inmutable)."""
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from apps.songs.models import SongRequest


def build_playlist_snapshot(event):
    """Copia de la playlist tal como quedó: canciones en orden de llegada, estado, quién la pidió y votos."""
    songs = (
        event.requests.select_related("guest")
        .annotate(rating_avg=Avg("ratings__stars"), rating_n=Count("ratings"))
        .order_by("created_at")
    )
    items = []
    for position, s in enumerate(songs, start=1):
        items.append({
            "position": position,
            "title": s.title,
            "artist": s.artist,
            "genre": s.get_genre_display(),
            "status": s.status,
            "status_label": s.get_status_display(),
            "requester": s.guest.display_name,
            "requester_email": s.guest.email,
            "link": s.reference_url,
            "platform": s.platform,
            "video_title": (s.youtube_data or {}).get("title", ""),
            "thumbnail": s.thumbnail_url,
            "rating_avg": round(s.rating_avg, 1) if s.rating_avg is not None else None,
            "rating_n": s.rating_n,
            "requested_at": timezone.localtime(s.created_at).isoformat(),
        })
    ratings = event.experience_ratings.aggregate(
        venue=Avg("venue_stars"), event=Avg("event_stars"), dj=Avg("dj_stars"), n=Count("id"))
    return {
        "songs": items,
        "summary": {
            "total": len(items),
            "played": sum(1 for i in items if i["status"] == SongRequest.Status.PLAYED),
            "pending": sum(1 for i in items if i["status"] == SongRequest.Status.PENDING),
            "rejected": sum(1 for i in items if i["status"] == SongRequest.Status.REJECTED),
            "people": len({i["requester_email"] for i in items}),
            "ratings": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in ratings.items()},
        },
    }


@transaction.atomic
def finalize_event(event, user):
    """Cierra el evento para siempre y guarda la copia de su playlist. Idempotente."""
    if event.finalized_at:
        return event
    event.playlist_snapshot = build_playlist_snapshot(event)
    event.finalized_at = timezone.now()
    event.finalized_by = user
    event.is_open = False
    event.accepting_requests = False
    event.closed_at = event.closed_at or event.finalized_at
    event.save(update_fields=["playlist_snapshot", "finalized_at", "finalized_by", "is_open",
                              "accepting_requests", "closed_at"])
    return event
