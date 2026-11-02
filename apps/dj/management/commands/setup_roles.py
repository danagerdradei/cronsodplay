from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from apps.dj.permissions import ADMIN_GROUP, DJ_GROUP

DJ_PERMISSIONS = [
    ("songs", "view_songrequest"),
    ("songs", "change_songrequest"),
    ("venues", "view_venue"),
    ("events", "view_event"),
    ("events", "add_event"),
    ("events", "change_event"),
    ("songs", "view_guest"),
    ("songs", "add_limitreset"),
]
ADMIN_APPS = ["songs", "venues", "events", "auth"]


class Command(BaseCommand):
    help = "Crea/actualiza los grupos de perfiles: DJ y Administrador. Es idempotente."

    def handle(self, *args, **options):
        dj, _ = Group.objects.get_or_create(name=DJ_GROUP)
        dj.permissions.set(
            Permission.objects.get(content_type__app_label=app, codename=code) for app, code in DJ_PERMISSIONS
        )

        admin, _ = Group.objects.get_or_create(name=ADMIN_GROUP)
        admin.permissions.set(Permission.objects.filter(content_type__app_label__in=ADMIN_APPS))

        self.stdout.write(self.style.SUCCESS(f"Grupos listos: {DJ_GROUP}, {ADMIN_GROUP}"))
