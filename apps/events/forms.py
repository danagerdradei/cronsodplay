from django import forms
from django.db import transaction

from apps.songs.models import SongRequest, normalize_key
from apps.venues.models import Venue

from .models import Event


class EventForm(forms.ModelForm):
    """Crear evento. Permite elegir una discoteca existente o crear una nueva en el mismo paso."""

    new_venue = forms.BooleanField(required=False, widget=forms.HiddenInput)
    new_venue_name = forms.CharField(
        label="Nombre de la discoteca / bar", max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ej: La Terraza Club"}),
    )
    new_venue_city = forms.CharField(
        label="Ciudad", max_length=80, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ej: Medellín"}),
    )

    allowed_genres = forms.MultipleChoiceField(
        label="Géneros de la noche", required=False, choices=SongRequest.Genre.choices,
        widget=forms.CheckboxSelectMultiple,
        help_text="Marca los géneros que vas a tocar. Si no marcas ninguno, se acepta cualquier género.",
    )

    class Meta:
        model = Event
        fields = ("name", "venue", "max_per_person", "allowed_genres")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Viernes Urbano"}),
            "max_per_person": forms.NumberInput(attrs={"min": 1, "max": 20, "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        venues = Venue.objects.filter(is_active=True)
        self.fields["venue"].queryset = venues
        self.fields["venue"].required = False  # puede venir una discoteca nueva
        self.fields["venue"].empty_label = "Elige la discoteca"
        active = list(venues[:2])
        if not self.is_bound:
            if len(active) == 1:
                self.initial.setdefault("venue", active[0].pk)
            elif not active:  # aún no hay discotecas: se muestra directo el formulario de nueva
                self.initial["new_venue"] = True

    @property
    def creating_venue(self):
        value = self["new_venue"].value()
        return value in (True, "True", "true", "1", "on")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_venue"):
            name = " ".join((cleaned.get("new_venue_name") or "").split())
            if not name:
                self.add_error("new_venue_name", "Escribe el nombre de la discoteca o bar.")
                return cleaned
            existing = next(
                (v for v in Venue.objects.all() if normalize_key(v.name) == normalize_key(name)), None
            )
            if existing and not existing.is_active:
                self.add_error("new_venue_name", "Esa discoteca existe pero está desactivada. Actívala en el Admin.")
            cleaned["new_venue_name"] = name
            cleaned["existing_venue"] = existing
        elif not cleaned.get("venue"):
            self.add_error("venue", "Elige la discoteca o crea una nueva.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        event = super().save(commit=False)
        if self.cleaned_data.get("new_venue"):
            # Si ya existe con ese nombre (sin importar mayúsculas/tildes) se reutiliza: no se duplica.
            venue = self.cleaned_data.get("existing_venue") or Venue.objects.create(
                name=self.cleaned_data["new_venue_name"], city=self.cleaned_data.get("new_venue_city", "")
            )
            event.venue = venue
        if commit:
            event.save()
        return event
