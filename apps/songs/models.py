import re
import unicodedata

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def normalize_key(value):
    """Normaliza texto para detectar canciones repetidas (sin tildes, minúsculas, sin signos)."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


class Guest(models.Model):
    """Persona que escanea el QR. No tiene usuario ni contraseña: su identificador es el correo."""

    email = models.EmailField("correo", unique=True)
    first_name = models.CharField("nombres", max_length=80)
    last_name = models.CharField("apellidos", max_length=80)
    alias = models.CharField("alias", max_length=40, blank=True)
    # Alias normalizado (sin tildes/mayúsculas): un alias pertenece a un solo correo.
    alias_key = models.CharField(max_length=40, blank=True, editable=False, db_index=True)
    phone = models.CharField("celular", max_length=20)
    # Cuenta de Google con la que inicia sesión ("sub" del ID token: estable aunque cambie el correo).
    google_sub = models.CharField("cuenta de Google", max_length=64, unique=True, null=True, blank=True, editable=False)
    picture_url = models.URLField("foto", max_length=500, blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "asistente"
        verbose_name_plural = "asistentes"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["alias_key"], condition=~models.Q(alias_key=""), name="unique_guest_alias"),
        ]

    def __str__(self):
        return f"{self.display_name} <{self.email}>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def display_name(self):
        return self.alias or self.full_name

    @property
    def public_name(self):
        """Lo que ve el público en la cola: alias o solo el primer nombre."""
        return self.alias or self.first_name.split(" ")[0]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.alias_key = normalize_key(self.alias)[:40]
        super().save(*args, **kwargs)


class SongRequest(models.Model):
    class Genre(models.TextChoices):
        REGGAETON = "reggaeton", "Reggaetón"
        DANCEHALL = "dancehall", "Dancehall"
        REGGAE = "reggae", "Reggae"
        SALSA = "salsa", "Salsa"
        MERENGUE = "merengue", "Merengue"
        BACHATA = "bachata", "Bachata"
        VALLENATO = "vallenato", "Vallenato"
        CHAMPETA = "champeta", "Champeta"
        CUMBIA = "cumbia", "Cumbia"
        ELECTRONICA = "electronica", "Electrónica"
        HOUSE = "house", "House / Tech House"
        POP = "pop", "Pop"
        ROCK = "rock", "Rock"
        HIPHOP = "hiphop", "Hip-Hop / Rap"
        URBANO = "urbano", "Urbano / Trap"
        CROSSOVER = "crossover", "Crossover"
        OTRO = "otro", "Otro"

    class Platform(models.TextChoices):
        NONE = "", "Sin enlace"
        YOUTUBE = "youtube", "YouTube"
        SPOTIFY = "spotify", "Spotify"

    class Status(models.TextChoices):
        PENDING = "pending", "En cola"
        PLAYED = "played", "Sonó 🎉"
        REJECTED = "rejected", "No disponible"

    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="requests", verbose_name="asistente")
    venue = models.ForeignKey(
        "venues.Venue", on_delete=models.PROTECT, related_name="requests", verbose_name="discoteca / bar"
    )
    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True, related_name="requests",
        verbose_name="evento",
    )
    # False cuando el DJ restablece el cupo: la canción sigue en la cola pero ya no cuenta para el límite.
    counts_toward_limit = models.BooleanField("cuenta para el límite", default=True)
    title = models.CharField("canción", max_length=150)
    artist = models.CharField("artista", max_length=120)
    genre = models.CharField("género", max_length=20, choices=Genre.choices)
    reference_url = models.URLField("enlace de referencia", blank=True)
    platform = models.CharField("plataforma", max_length=10, choices=Platform.choices, blank=True)
    thumbnail_url = models.URLField("portada", max_length=500, blank=True)
    # Vistas, likes, duración y recomendación calculada a partir de los comentarios (ver analysis.py).
    youtube_data = models.JSONField("datos de YouTube", default=dict, blank=True, editable=False)
    youtube_fetched_at = models.DateTimeField("YouTube consultado", null=True, blank=True, editable=False)
    status = models.CharField("estado", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    # Datos de control anti-abuso: solo visibles para el Admin.
    client_ip = models.GenericIPAddressField("IP pública", null=True, blank=True, editable=False)
    device_id = models.CharField("dispositivo", max_length=32, blank=True, editable=False, db_index=True)
    title_key = models.CharField(max_length=150, editable=False)
    artist_key = models.CharField(max_length=120, editable=False)
    created_at = models.DateTimeField("solicitada", auto_now_add=True, db_index=True)
    status_changed_at = models.DateTimeField("cambio de estado", null=True, blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_requests",
        verbose_name="atendida por",
    )

    class Meta:
        verbose_name = "solicitud de canción"
        verbose_name_plural = "solicitudes de canciones"
        # Prioridad = orden de llegada.
        ordering = ["created_at"]
        constraints = [
            # Una persona no repite canción en el mismo evento (ni entre pedidos sin evento).
            models.UniqueConstraint(
                fields=["guest", "title_key", "artist_key"], condition=models.Q(event__isnull=True),
                name="unique_song_per_guest",
            ),
            models.UniqueConstraint(
                fields=["guest", "event", "title_key", "artist_key"], condition=models.Q(event__isnull=False),
                name="unique_song_per_guest_event",
            ),
        ]
        indexes = [
            models.Index(fields=["venue", "status", "created_at"]),
            models.Index(fields=["client_ip", "created_at"]),
        ]

    def __str__(self):
        return f"{self.title} — {self.artist}"

    def save(self, *args, **kwargs):
        self.title_key = normalize_key(self.title)
        self.artist_key = normalize_key(self.artist)
        self.platform = detect_platform(self.reference_url)
        super().save(*args, **kwargs)


def detect_platform(url):
    url = (url or "").lower()
    if "spotify.com" in url:
        return SongRequest.Platform.SPOTIFY
    if "youtube.com" in url or "youtu.be" in url:
        return SongRequest.Platform.YOUTUBE
    return SongRequest.Platform.NONE


class SongRating(models.Model):
    """Puntuación de 1 a 5 estrellas que da el público a una canción de la cola (una por dispositivo)."""

    song = models.ForeignKey(SongRequest, on_delete=models.CASCADE, related_name="ratings", verbose_name="canción")
    device_id = models.CharField("dispositivo", max_length=32)
    stars = models.PositiveSmallIntegerField("estrellas", validators=[MinValueValidator(1), MaxValueValidator(5)])
    client_ip = models.GenericIPAddressField("IP pública", null=True, blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "puntuación"
        verbose_name_plural = "puntuaciones"
        constraints = [
            models.UniqueConstraint(fields=["song", "device_id"], name="one_rating_per_device"),
            models.CheckConstraint(condition=models.Q(stars__gte=1, stars__lte=5), name="stars_1_to_5"),
        ]

    def __str__(self):
        return f"{self.song} — {self.stars}★"


class LimitReset(models.Model):
    """Registro de cada vez que el DJ/Admin restablece el cupo de una persona."""

    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="limit_resets", verbose_name="asistente")
    event = models.ForeignKey(
        "events.Event", on_delete=models.SET_NULL, null=True, blank=True, related_name="limit_resets",
        verbose_name="evento",
    )
    reset_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="limit_resets",
        verbose_name="restablecido por",
    )
    songs_released = models.PositiveIntegerField("canciones liberadas", default=0)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        verbose_name = "restablecimiento de límite"
        verbose_name_plural = "restablecimientos de límite"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.guest.display_name} · {self.songs_released} liberadas"


STARS = [MinValueValidator(1), MaxValueValidator(5)]


class ExperienceRating(models.Model):
    """
    Calificación de la noche (1-5 estrellas): local, evento y DJ. Es obligatoria al pedir la
    última canción del cupo (con cupo de 3, la 3ra) y se pide una sola vez por evento.
    """

    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="experience_ratings", verbose_name="asistente")
    venue = models.ForeignKey("venues.Venue", on_delete=models.CASCADE, related_name="experience_ratings",
                              verbose_name="discoteca / bar")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, null=True, blank=True,
                              related_name="experience_ratings", verbose_name="evento")
    dj = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="experience_ratings", verbose_name="DJ")
    song = models.OneToOneField(SongRequest, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="experience_rating", verbose_name="canción con la que calificó")
    venue_stars = models.PositiveSmallIntegerField("estrellas al local", validators=STARS)
    event_stars = models.PositiveSmallIntegerField("estrellas al evento", null=True, blank=True, validators=STARS)
    dj_stars = models.PositiveSmallIntegerField("estrellas al DJ", null=True, blank=True, validators=STARS)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        verbose_name = "calificación de la noche"
        verbose_name_plural = "calificaciones de la noche"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["guest", "event"], condition=models.Q(event__isnull=False),
                                    name="one_experience_per_event"),
            models.CheckConstraint(condition=models.Q(venue_stars__gte=1, venue_stars__lte=5), name="venue_stars_1_5"),
            models.CheckConstraint(condition=models.Q(event_stars__isnull=True) | models.Q(event_stars__gte=1, event_stars__lte=5),
                                   name="event_stars_1_5"),
            models.CheckConstraint(condition=models.Q(dj_stars__isnull=True) | models.Q(dj_stars__gte=1, dj_stars__lte=5),
                                   name="dj_stars_1_5"),
        ]

    def __str__(self):
        return f"{self.guest.display_name} · local {self.venue_stars}★"
