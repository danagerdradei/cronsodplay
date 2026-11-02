from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Venue(models.Model):
    """Discoteca o bar donde se ubica el QR."""

    name = models.CharField("nombre", max_length=120, unique=True)
    slug = models.SlugField("slug", max_length=140, unique=True, blank=True)
    city = models.CharField("ciudad", max_length=80, blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)

    class Meta:
        verbose_name = "discoteca / bar"
        verbose_name_plural = "discotecas / bares"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            # "Cronso-Club" y "Cronso Club" darían el mismo slug: se agrega un sufijo.
            base = slugify(self.name)[:130] or "discoteca"
            slug, n = base, 2
            while Venue.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("venues:entry", args=[self.slug])

    @property
    def public_url(self):
        """URL completa que se codifica en el QR."""
        return settings.PUBLIC_BASE_URL.rstrip("/") + self.get_absolute_url()
