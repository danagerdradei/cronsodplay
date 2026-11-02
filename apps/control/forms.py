from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import Group, User

from apps.dj.permissions import ADMIN_GROUP, DJ_GROUP
from apps.venues.models import Venue

ROLE_CHOICES = [("dj", "DJ"), ("admin", "Admin (control total)")]


def apply_role(user, role):
    """DJ: grupo DJ, sin /admin/. Admin: grupo Administrador + acceso al /admin/."""
    dj, admin = Group.objects.get(name=DJ_GROUP), Group.objects.get(name=ADMIN_GROUP)
    if role == "admin":
        user.is_staff = True
        user.groups.add(admin)
        user.groups.remove(dj)
    else:
        if not user.is_superuser:
            user.is_staff = False
        user.groups.add(dj)
        user.groups.remove(admin)
    user.save()


def role_of(user):
    return "admin" if user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists() else "dj"


class _PasswordMixin(forms.Form):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repite la contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            try:
                password_validation.validate_password(p1, getattr(self, "user_for_validation", None))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class StaffCreateForm(_PasswordMixin):
    username = forms.CharField(label="Usuario", max_length=150,
                               widget=forms.TextInput(attrs={"autocapitalize": "none", "placeholder": "Ej: dj_cronso"}))
    first_name = forms.CharField(label="Nombre artístico / nombre", max_length=150, required=False,
                                 widget=forms.TextInput(attrs={"placeholder": "Ej: DJ Cronso"}))
    role = forms.ChoiceField(label="Rol", choices=ROLE_CHOICES, initial="dj")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ese usuario ya existe.")
        return username

    def save(self):
        user = User.objects.create_user(
            username=self.cleaned_data["username"], password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
        )
        apply_role(user, self.cleaned_data["role"])
        return user


class StaffEditForm(forms.Form):
    first_name = forms.CharField(label="Nombre artístico / nombre", max_length=150, required=False)
    role = forms.ChoiceField(label="Rol", choices=ROLE_CHOICES)
    is_active = forms.BooleanField(label="Activo (puede iniciar sesión)", required=False)


class StaffPasswordForm(_PasswordMixin):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_for_validation = user


class VenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ("name", "city")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: La Terraza Club"}),
            "city": forms.TextInput(attrs={"placeholder": "Ej: Medellín"}),
        }
