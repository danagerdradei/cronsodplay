from django.core.management.base import BaseCommand, CommandError

from apps.songs import youtube
from apps.songs.models import SongRequest
from apps.songs.services import enrich_youtube


class Command(BaseCommand):
    help = "Consulta YouTube (vistas, likes, recomendación) para las solicitudes que no lo tengan."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Volver a consultar todas (actualiza vistas y likes)")
        parser.add_argument("--status", default="pending", help="pending | played | rejected | all (por defecto: pending)")

    def handle(self, all, status, **options):
        if not youtube.is_configured():
            raise CommandError("Falta YOUTUBE_API_KEY en el entorno.")
        qs = SongRequest.objects.order_by("created_at")
        if status != "all":
            qs = qs.filter(status=status)
        if not all:
            qs = qs.filter(youtube_fetched_at__isnull=True)
        total = qs.count()
        ok = sum(1 for song in qs.iterator() if enrich_youtube(song, use_cache=not all))
        self.stdout.write(self.style.SUCCESS(f"YouTube actualizado: {ok} de {total}"))
