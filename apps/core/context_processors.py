from django.conf import settings


def app_info(request):
    """Datos globales disponibles en todas las plantillas."""
    return {
        "APP_NAME": settings.APP_NAME,
        "SONG_MAX_PER_EMAIL": settings.SONG_MAX_PER_EMAIL,
        "QUOTA_SLOTS": range(1, settings.SONG_MAX_PER_EMAIL + 1),
    }
