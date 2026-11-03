import re
from urllib.parse import urlparse

from django import forms

from apps.venues.models import Venue

from .models import SongRequest

ALLOWED_LINK_HOSTS = ("youtube.com", "youtu.be", "spotify.com")
STAR_CHOICES = [(n, str(n)) for n in range(1, 6)]


def _join_labels(labels):
    """['Reggaetón', 'Salsa', 'Pop'] -> 'Reggaetón, Salsa y Pop'."""
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " y " + labels[-1]


class SongRequestForm(forms.Form):
    # --- Datos de la persona ---
    first_name = forms.CharField(label="Nombres", max_length=80)
    last_name = forms.CharField(label="Apellidos", max_length=80)
    alias = forms.CharField(label="Alias", max_length=40, required=False)
    phone = forms.CharField(label="Celular", max_length=20)
    email = forms.EmailField(label="Correo")
    venue = forms.ModelChoiceField(
        label="Discoteca / Bar",
        queryset=Venue.objects.filter(is_active=True),
        empty_label="Selecciona dónde estás",
    )
    # --- Datos de la canción ---
    title = forms.CharField(label="Nombre de la canción", max_length=150)
    artist = forms.CharField(label="Artista", max_length=120)
    genre = forms.ChoiceField(label="Género", choices=[("", "Elige un género")] + SongRequest.Genre.choices)
    reference_url = forms.URLField(label="Link de YouTube o Spotify", required=False, assume_scheme="https")

    # Calificación de la noche (solo se muestra y exige en la última canción del cupo).
    venue_stars = forms.TypedChoiceField(choices=STAR_CHOICES, coerce=int, required=False, empty_value=None)
    event_stars = forms.TypedChoiceField(choices=STAR_CHOICES, coerce=int, required=False, empty_value=None)
    dj_stars = forms.TypedChoiceField(choices=STAR_CHOICES, coerce=int, required=False, empty_value=None)

    GUEST_FIELDS = ("first_name", "last_name", "alias", "phone", "email")
    SONG_FIELDS = ("venue", "title", "artist", "genre", "reference_url")

    def __init__(self, *args, event=None, guest=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.guest = guest  # asistente con sesión de Google: nombres y correo vienen de su perfil
        if guest is not None:
            for name in ("first_name", "last_name", "email"):
                del self.fields[name]
            if guest.alias:
                self.fields["alias"].disabled = True
                self.fields["alias"].initial = guest.alias
        if event is not None and event.allowed_genres:
            labels = event.genre_labels
            allowed = [(c, l) for c, l in SongRequest.Genre.choices if c in event.allowed_genres]
            self.fields["genre"].choices = [("", "Elige un género")] + allowed
            self.fields["genre"].error_messages["invalid_choice"] = (
                f"Este evento es solo de {_join_labels(labels)}. Elige uno de esos géneros "
                f"o pide tu canción en otro evento."
            )
        attrs = {
            "first_name": {"autocomplete": "given-name", "placeholder": "Ej: María José"},
            "last_name": {"autocomplete": "family-name", "placeholder": "Ej: Pérez Gómez"},
            "alias": {"placeholder": "Cómo te anuncia el DJ (opcional)"},
            "phone": {"autocomplete": "tel", "inputmode": "tel", "placeholder": "Ej: 300 123 4567"},
            "email": {"autocomplete": "email", "inputmode": "email", "placeholder": "tucorreo@ejemplo.com"},
            "title": {"placeholder": "Ej: My Name Is"},
            "artist": {"placeholder": "Ej: Eminem"},
            "reference_url": {"inputmode": "url", "autocomplete": "off", "spellcheck": "false",
                              "placeholder": "https://open.spotify.com/... o https://youtu.be/..."},
        }
        for name, extra in attrs.items():
            if name in self.fields:  # con sesión de Google, nombres y correo no están en el formulario
                self.fields[name].widget.attrs.update(extra)

    def lock_identity(self, guest):
        if self.guest is not None:  # con Google esos campos ni siquiera están en el formulario
            return
        """Asistente conocido en este dispositivo: sus datos de identidad no se pueden cambiar."""
        locked = ["first_name", "last_name", "email"] + (["alias"] if guest.alias else [])
        for name in locked:
            self.fields[name].widget.attrs.update({"readonly": True, "class": "locked"})

    def clean_alias(self):
        return " ".join(self.cleaned_data["alias"].split())

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip().title()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip().title()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        digits = re.sub(r"\D", "", phone)
        if not re.fullmatch(r"\+?[\d\s\-()]+", phone) or not 7 <= len(digits) <= 15:
            raise forms.ValidationError("Escribe un número de celular válido.")
        return phone

    def clean_reference_url(self):
        url = self.cleaned_data["reference_url"]
        if not url:
            return url
        host = (urlparse(url).hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in ALLOWED_LINK_HOSTS):
            raise forms.ValidationError("Solo aceptamos enlaces de YouTube o Spotify.")
        return url

    def guest_data(self):
        if self.guest is not None:
            return {
                "first_name": self.guest.first_name, "last_name": self.guest.last_name, "email": self.guest.email,
                "alias": self.guest.alias or self.cleaned_data.get("alias", ""), "phone": self.cleaned_data["phone"],
            }
        return {f: self.cleaned_data[f] for f in self.GUEST_FIELDS}

    def experience_data(self):
        return {f: self.cleaned_data.get(f) for f in ("venue_stars", "event_stars", "dj_stars")}

    def song_data(self):
        return {f: self.cleaned_data[f] for f in self.SONG_FIELDS}


class EmailLookupForm(forms.Form):
    email = forms.EmailField(
        label="Correo con el que pediste",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "inputmode": "email", "placeholder": "tucorreo@ejemplo.com"}),
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
