from django.utils import timezone

from apps.songs.api import rating_summary


def serialize_youtube(data):
    """Resumen de YouTube para el DJ: estadísticas + recomendación (sin textos de comentarios)."""
    if not data or not data.get("video_id"):
        return None
    analysis = data.get("analysis") or {}
    return {
        "url": f"https://www.youtube.com/watch?v={data['video_id']}",
        "title": data.get("title", ""),
        "views": data.get("views"),
        "likes": data.get("likes"),
        "duration": data.get("duration"),
        "found_by_search": data.get("source") == "search",
        "moment": analysis.get("moment"),
        "moment_label": analysis.get("moment_label"),
        "tags": analysis.get("tags", []),
        "highlight": analysis.get("highlight"),
        "comments_analyzed": analysis.get("comments_analyzed", 0),
        "low_confidence": analysis.get("low_confidence", True),
    }


def serialize_request(song, position=None):
    """Representación JSON de una solicitud para el DJ (sin correo ni celular)."""
    created = timezone.localtime(song.created_at)
    return {
        "id": song.pk,
        "position": position,
        "title": song.title,
        "artist": song.artist,
        "genre": song.genre,
        "genre_label": song.get_genre_display(),
        "reference_url": song.reference_url,
        "platform": song.platform,
        "thumbnail_url": song.thumbnail_url,
        "youtube": serialize_youtube(song.youtube_data),
        "rating": rating_summary(song),
        "requester": song.guest.display_name,
        "venue": {"slug": song.venue.slug, "name": song.venue.name},
        "event": song.event.name if song.event_id else None,
        "status": song.status,
        "status_label": song.get_status_display(),
        "created_at": created.isoformat(),
        "created_at_display": created.strftime("%I:%M %p").lstrip("0"),
    }


def mask_email(email):
    """'elputres@hotmail.com' -> 'el******@hotmail.com' (el DJ busca por correo sin verlo completo)."""
    user, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    visible = user[:2] if len(user) > 3 else user[:1]
    return f"{visible}{'*' * max(len(user) - len(visible), 3)}@{domain}"
