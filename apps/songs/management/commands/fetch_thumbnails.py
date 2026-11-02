from django.core.management.base import BaseCommand

from apps.songs.models import SongRequest
from apps.songs.services import attach_thumbnail


class Command(BaseCommand):
    help = "Obtiene las portadas faltantes de las solicitudes con link de YouTube/Spotify."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recalcular también las que ya tienen portada")

    def handle(self, all, **options):
        qs = SongRequest.objects.exclude(reference_url="")
        if not all:
            qs = qs.filter(thumbnail_url="")
        total = qs.count()
        found = sum(1 for song in qs.iterator() if attach_thumbnail(song))
        self.stdout.write(self.style.SUCCESS(f"Portadas obtenidas: {found} de {total}"))
