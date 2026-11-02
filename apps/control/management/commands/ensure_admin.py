import os

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from apps.dj.permissions import ADMIN_GROUP


class Command(BaseCommand):
    help = (
        "Crea el Admin de la plataforma con DJANGO_SUPERUSER_USERNAME/PASSWORD si no existe. "
        "Si ya existe, solo asegura sus privilegios (no cambia la contraseña). Idempotente."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        user = User.objects.filter(username=username).first()
        if user is None:
            if not password:
                self.stdout.write(self.style.WARNING("Sin DJANGO_SUPERUSER_PASSWORD: no se creó el Admin."))
                return
            user = User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Admin «{username}» creado."))
        else:
            user.is_superuser = user.is_staff = user.is_active = True
            user.save(update_fields=["is_superuser", "is_staff", "is_active"])
            self.stdout.write(f"Admin «{username}» ya existe: privilegios verificados.")
        group = Group.objects.filter(name=ADMIN_GROUP).first()
        if group:
            user.groups.add(group)
