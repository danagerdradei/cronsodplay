"""
Reglas de negocio de solicitudes de canciones.

Las vistas no deben crear SongRequest directamente: siempre pasan por
`register_song_request`, que aplica los límites (correo, dispositivo e IP) y evita
duplicados de forma segura ante peticiones concurrentes (bloqueo de fila del asistente).
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.net import ip_in_list

from . import youtube
from .analysis import analyze
from .models import ExperienceRating, Guest, LimitReset, SongRequest, normalize_key
from .thumbnails import fetch_thumbnail, youtube_video_id

logger = logging.getLogger(__name__)


class SongRequestError(Exception):
    pass


class LimitReached(SongRequestError):
    """`reason` es 'email', 'device' o 'ip'. Solo 'email' se explica al usuario."""

    def __init__(self, reason="email"):
        super().__init__(reason)
        self.reason = reason


class DuplicateSong(SongRequestError):
    pass


class IdentityMismatch(SongRequestError):
    """El correo ya está registrado con otros nombres/alias. `fields` = campos que no coinciden."""

    def __init__(self, fields):
        super().__init__(", ".join(fields))
        self.fields = fields


class AliasTaken(SongRequestError):
    """El alias ya pertenece a otro correo."""


class GenreNotAllowed(SongRequestError):
    """El evento no acepta ese género."""


class ExperienceRequired(SongRequestError):
    """Es la última canción del cupo: hay que calificar la noche. `fields` = estrellas que faltan."""

    def __init__(self, fields):
        super().__init__(", ".join(fields))
        self.fields = fields


EXPERIENCE_FIELDS = ("venue_stars", "event_stars", "dj_stars")


def experience_targets(event=None, venue=None):
    """Qué se califica: siempre el local; el evento y su DJ solo si se pide desde un evento."""
    venue = event.venue if event is not None else venue
    dj = event.dj if event is not None else None
    return {
        "venue": venue,
        "event": event,
        "dj": dj,
        "dj_name": (dj.get_short_name() or dj.username) if dj else "",
        "fields": ["venue_stars"] + (["event_stars"] if event else []) + (["dj_stars"] if dj else []),
    }


def already_rated(guest, event=None, venue=None):
    if guest is None or guest.pk is None:
        return False
    qs = ExperienceRating.objects.filter(guest=guest)
    if event is not None:
        return qs.filter(event=event).exists()
    since = _since(settings.SONG_LIMIT_WINDOW_HOURS or 12)  # sin evento: una vez por noche
    return qs.filter(event__isnull=True, venue=venue, created_at__gte=since).exists()


def needs_experience(guest, event=None, venue=None):
    """True si la próxima canción de esta persona es la última de su cupo y aún no calificó la noche."""
    per_person, _ = limits_for(event)
    used = requests_counted_for_limit(guest, event) if guest is not None and guest.pk else 0
    return used + 1 >= per_person and not already_rated(guest, event, venue)


IDENTITY_FIELDS = ("first_name", "last_name", "alias")


def alias_taken(alias, email):
    key = normalize_key(alias)[:40]
    return bool(key) and Guest.objects.filter(alias_key=key).exclude(email=email).exists()


def identity_mismatches(guest, guest_data):
    """
    Campos de identidad que no coinciden con los registrados la primera vez (sin distinguir
    mayúsculas, tildes ni espacios). Un alias en blanco significa "seguir con el registrado".
    """
    mismatched = []
    for field in IDENTITY_FIELDS:
        submitted, stored = guest_data.get(field, ""), getattr(guest, field)
        if field == "alias" and (not submitted or not stored):
            continue
        if normalize_key(submitted) != normalize_key(stored):
            mismatched.append(field)
    return mismatched


def _get_or_create_guest(email, guest_data):
    """
    Correo nuevo: crea el asistente (el alias no puede ser de otro correo).
    Correo conocido: nombres y alias deben coincidir con los de la primera vez; solo se
    actualiza el celular, y se puede agregar un alias si antes no tenía.
    """
    guest = Guest.objects.select_for_update().filter(email=email).first()
    if guest is None:
        if alias_taken(guest_data.get("alias", ""), email):
            raise AliasTaken()
        try:
            with transaction.atomic():  # savepoint: un IntegrityError no invalida la transacción externa
                return Guest.objects.create(email=email, **{k: v for k, v in guest_data.items() if k != "email"})
        except IntegrityError:
            # Otro pedido creó este correo en paralelo, o tomó el mismo alias.
            guest = Guest.objects.select_for_update().filter(email=email).first()
            if guest is None:
                raise AliasTaken() from None

    mismatched = identity_mismatches(guest, guest_data)
    if mismatched:
        raise IdentityMismatch(mismatched)
    alias = guest_data.get("alias", "")
    if alias and not guest.alias:
        if alias_taken(alias, email):
            raise AliasTaken()
        guest.alias = alias
    guest.phone = guest_data.get("phone") or guest.phone
    guest.save()
    return guest


def _since(hours):
    return timezone.now() - timedelta(hours=hours) if hours > 0 else None


def _count(qs, hours):
    start = _since(hours)
    return (qs.filter(created_at__gte=start) if start else qs).count()


def limits_for(event=None):
    """(máximo por persona/correo, máximo por dispositivo). Con evento manda el cupo del evento."""
    per_person = event.max_per_person if event else settings.SONG_MAX_PER_EMAIL
    per_device = 0
    if settings.SONG_MAX_PER_DEVICE:
        per_device = event.max_per_person if event else settings.SONG_MAX_PER_DEVICE
    return per_person, per_device


def limit_scope(qs, event=None):
    """
    Solicitudes que cuentan para el cupo: las del evento, o (sin evento) las que no
    son de ningún evento dentro de SONG_LIMIT_WINDOW_HOURS. Excluye las liberadas por el DJ.
    """
    qs = qs.filter(counts_toward_limit=True)
    if event is not None:
        return qs.filter(event=event)
    qs = qs.filter(event__isnull=True)
    start = _since(settings.SONG_LIMIT_WINDOW_HOURS)
    return qs.filter(created_at__gte=start) if start else qs


def requests_counted_for_limit(guest, event=None):
    return limit_scope(guest.requests.all(), event).count()


def remaining_for_email(email, event=None):
    """Canciones que aún puede pedir un correo (para mostrar en el formulario)."""
    per_person, _ = limits_for(event)
    guest = Guest.objects.filter(email=(email or "").strip().lower()).first()
    used = requests_counted_for_limit(guest, event) if guest else 0
    return max(per_person - used, 0)


def remaining_for_device(device_id, event=None):
    """Canciones que aún se pueden pedir desde este dispositivo (None = sin límite)."""
    _, per_device = limits_for(event)
    if not per_device or not device_id:
        return None
    used = limit_scope(SongRequest.objects.filter(device_id=device_id), event).count()
    return max(per_device - used, 0)


def ip_limit_reached(client_ip):
    if not settings.SONG_MAX_PER_IP or not client_ip or ip_in_list(client_ip, settings.SONG_IP_ALLOWLIST):
        return False
    qs = SongRequest.objects.filter(client_ip=client_ip, counts_toward_limit=True)
    return _count(qs, settings.SONG_IP_WINDOW_HOURS) >= settings.SONG_MAX_PER_IP


def remaining(email=None, device_id=None, event=None):
    """Cupo efectivo: el menor entre el del correo y el del dispositivo."""
    per_person, _ = limits_for(event)
    values = [remaining_for_email(email, event) if email else per_person]
    device_left = remaining_for_device(device_id, event)
    if device_left is not None:
        values.append(device_left)
    return min(values)


def reset_limit(guest, user, event=None):
    """
    Restablece el cupo de una persona: sus canciones (y las de los dispositivos que usó)
    siguen en la cola, pero dejan de contar para el límite. Devuelve cuántas se liberaron.
    """
    devices = set(guest.requests.exclude(device_id="").values_list("device_id", flat=True))
    qs = limit_scope(SongRequest.objects.filter(Q(guest=guest) | Q(device_id__in=devices)), event)
    released = qs.update(counts_toward_limit=False)
    LimitReset.objects.create(guest=guest, event=event, reset_by=user, songs_released=released)
    return released


def register_song_request(*, guest_data, song_data, client_ip=None, device_id="", event=None, experience=None):
    """
    Crea (o actualiza) el asistente y registra su canción.

    Lanza LimitReached si se superó el cupo del correo, del dispositivo o de la IP,
    y DuplicateSong si esa misma canción ya fue pedida con ese correo (en el mismo evento).
    """
    email = guest_data["email"].strip().lower()
    if event is not None:
        if not event.allows_genre(song_data["genre"]):
            raise GenreNotAllowed()
        song_data = {**song_data, "venue": event.venue}
    per_person, _ = limits_for(event)
    with transaction.atomic():
        guest = _get_or_create_guest(email, guest_data)

        if requests_counted_for_limit(guest, event) >= per_person:
            raise LimitReached("email")
        if remaining_for_device(device_id, event) == 0:
            raise LimitReached("device")
        if ip_limit_reached(client_ip):
            raise LimitReached("ip")

        if guest.requests.filter(
            event=event,
            title_key=normalize_key(song_data["title"]),
            artist_key=normalize_key(song_data["artist"]),
        ).exists():
            raise DuplicateSong()

        # Última canción del cupo: calificar la noche es obligatorio (una vez por evento).
        targets = None
        if needs_experience(guest, event, song_data["venue"]):
            targets = experience_targets(event, song_data["venue"])
            experience = experience or {}
            missing = [f for f in targets["fields"] if not experience.get(f)]
            if missing:
                raise ExperienceRequired(missing)

        song = SongRequest.objects.create(
            guest=guest, event=event, client_ip=client_ip, device_id=device_id, **song_data
        )
        if targets is not None:
            ExperienceRating.objects.create(
                guest=guest, venue=targets["venue"], event=event, dj=targets["dj"], song=song,
                venue_stars=experience["venue_stars"],
                event_stars=experience.get("event_stars") if event else None,
                dj_stars=experience.get("dj_stars") if targets["dj"] else None,
            )

    # Fuera de la transacción: la llamada de red no debe mantener el bloqueo de fila.
    attach_thumbnail(song)
    enrich_in_background(song.pk)
    return song


def enrich_in_background(song_id):
    """Consulta YouTube (vistas, likes, comentarios) sin demorar la respuesta al usuario."""
    if not youtube.is_configured():
        return

    def run():
        try:
            enrich_youtube(SongRequest.objects.get(pk=song_id))
        finally:
            connection.close()  # el hilo abre su propia conexión a la BD

    if settings.ENRICH_ASYNC:
        threading.Thread(target=run, daemon=True, name=f"yt-enrich-{song_id}").start()
    else:
        enrich_youtube(SongRequest.objects.get(pk=song_id))


def _cached_youtube_data(song, video_id):
    """Datos recientes del mismo video (o de la misma canción buscada) para no gastar cuota."""
    since = timezone.now() - timedelta(hours=settings.YOUTUBE_CACHE_HOURS)
    qs = SongRequest.objects.exclude(pk=song.pk).exclude(youtube_data={}).filter(youtube_fetched_at__gte=since)
    if video_id:
        qs = qs.filter(youtube_data__video_id=video_id)
    else:
        qs = qs.filter(title_key=song.title_key, artist_key=song.artist_key)
    other = qs.order_by("-youtube_fetched_at").first()
    return other.youtube_data if other else None


def enrich_youtube(song, use_cache=True):
    """
    Guarda en song.youtube_data: vistas, likes, duración y la recomendación por comentarios.
    Nunca lanza excepciones: si YouTube falla, la canción queda sin estos datos.
    """
    if not youtube.is_configured():
        return None
    try:
        video_id = youtube_video_id(song.reference_url)
        source = "link"
        if not video_id and not settings.YOUTUBE_SEARCH_FALLBACK:
            return None

        data = _cached_youtube_data(song, video_id) if use_cache else None
        if data is None:
            if not video_id:
                video_id = youtube.search_video(f"{song.artist} {song.title}")
                source = "search"
                if not video_id:
                    return None
            data = youtube.video_details(video_id)
            if data is None:
                return None
            comments = youtube.top_comments(video_id, settings.YOUTUBE_COMMENTS_MAX)
            data["analysis"] = analyze(comments, data["views"], data["likes"], data["duration"])
            data["source"] = source

        song.youtube_data = data
        song.youtube_fetched_at = timezone.now()
        fields = ["youtube_data", "youtube_fetched_at"]
        if not song.thumbnail_url:
            song.thumbnail_url = f"https://i.ytimg.com/vi/{data['video_id']}/hqdefault.jpg"
            fields.append("thumbnail_url")
        song.save(update_fields=fields)
        return data
    except Exception as exc:  # noqa: BLE001 — cuota agotada, red, key inválida…
        logger.warning("No se pudo consultar YouTube para la solicitud %s: %s", song.pk, exc)
        return None


def attach_thumbnail(song):
    """Guarda la portada del link de YouTube/Spotify si se puede obtener."""
    thumb = fetch_thumbnail(song.reference_url)
    if thumb and thumb != song.thumbnail_url:
        song.thumbnail_url = thumb
        song.save(update_fields=["thumbnail_url"])
    return thumb
