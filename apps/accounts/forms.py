import re

from django import forms

from apps.songs.models import Guest


class ProfileForm(forms.ModelForm):
    """El asistente solo edita su celular y, si aún no tiene, su alias (luego queda fijo)."""

    class Meta:
        model = Guest
        fields = ("alias", "phone")
        labels = {"alias": "Alias", "phone": "Celular"}
        widgets = {
            "alias": forms.TextInput(attrs={"placeholder": "Cómo te anuncia el DJ (opcional)"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel", "placeholder": "Ej: 300 123 4567"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].required = True
        if self.instance.alias:
            self.fields["alias"].disabled = True  # el alias no se cambia una vez elegido

    def clean_alias(self):
        return " ".join((self.cleaned_data.get("alias") or "").split())

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        digits = re.sub(r"\D", "", phone)
        if not re.fullmatch(r"\+?[\d\s\-()]+", phone) or not 7 <= len(digits) <= 15:
            raise forms.ValidationError("Escribe un número de celular válido.")
        return phone
