from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.dj.permissions import DJ_GROUP


class Command(BaseCommand):
    help = "Crea un usuario DJ (sin acceso al /admin). Uso: create_dj <usuario> <contraseña>"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("password")
        parser.add_argument("--name", default="", help="Nombre artístico del DJ")

    def handle(self, username, password, name, **options):
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise CommandError(f"El usuario '{username}' ya existe.")
        group = Group.objects.filter(name=DJ_GROUP).first()
        if not group:
            raise CommandError("Ejecuta primero: python manage.py setup_roles")
        user = User.objects.create_user(username=username, password=password, first_name=name, is_staff=False)
        user.groups.add(group)
        self.stdout.write(self.style.SUCCESS(f"DJ '{username}' creado."))
