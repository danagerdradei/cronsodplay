import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

# Sin letras/números que se confundan al leerlos en voz alta o en un QR impreso (0/O, 1/I).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def new_event_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def default_max_per_person():
    return settings.SONG_MAX_PER_EMAIL


class Event(models.Model):
    """
    Una noche/fiesta creada por el DJ. Su link y QR llevan al formulario con la
    discoteca ya elegida, y el cupo de canciones se cuenta por evento.
    """

    name = models.CharField("nombre del evento", max_length=120)
    code = models.CharField("código", max_length=12, unique=True, default=new_event_code, editable=False)
    venue = models.ForeignKey(
        "venues.Venue", on_delete=models.PROTECT, related_name="events", verbose_name="discoteca / bar"
    )
    dj = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="events", verbose_name="creado por",
    )
    max_per_person = models.PositiveSmallIntegerField(
        "canciones por persona", default=default_max_per_person,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    # Códigos de SongRequest.Genre que acepta el evento. Vacío = todos los géneros.
    allowed_genres = models.JSONField("géneros permitidos", default=list, blank=True)
    is_open = models.BooleanField("abierto", default=True, db_index=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    closed_at = models.DateTimeField("cerrado", null=True, blank=True)

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} · {self.venue}"

    def save(self, *args, **kwargs):
        while Event.objects.filter(code=self.code).exclude(pk=self.pk).exists():
            self.code = new_event_code()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("events:entry", args=[self.code])

    def allows_genre(self, genre):
        return not self.allowed_genres or genre in self.allowed_genres

    @property
    def genre_labels(self):
        """Nombres legibles de los géneros permitidos, en el orden del catálogo."""
        from apps.songs.models import SongRequest

        return [label for code, label in SongRequest.Genre.choices if code in (self.allowed_genres or [])]

    @property
    def public_url(self):
        """URL completa que se comparte y se codifica en el QR."""
        return settings.PUBLIC_BASE_URL.rstrip("/") + self.get_absolute_url()
