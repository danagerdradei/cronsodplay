import csv

from django.contrib import admin
from django.http import HttpResponse
from django.utils import timezone

from .models import ExperienceRating, Guest, LimitReset, SongRating, SongRequest


class SongRequestInline(admin.TabularInline):
    model = SongRequest
    extra = 0
    fields = ("title", "artist", "genre", "venue", "status", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "alias", "phone", "total_requests", "created_at")
    search_fields = ("email", "first_name", "last_name", "alias", "phone")
    inlines = [SongRequestInline]

    @admin.display(description="Canciones")
    def total_requests(self, obj):
        return obj.requests.count()


@admin.register(SongRequest)
class SongRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "genre", "venue", "requester", "status", "yt_views", "yt_moment", "client_ip", "created_at")
    list_filter = ("status", "venue", "event", "genre", "platform", "created_at")
    search_fields = ("title", "artist", "guest__email", "guest__first_name", "guest__alias", "client_ip", "device_id")
    list_select_related = ("guest", "venue")
    readonly_fields = (
        "platform", "thumbnail_url", "youtube_data", "youtube_fetched_at", "client_ip", "device_id",
        "title_key", "artist_key", "created_at", "status_changed_at", "handled_by",
    )
    date_hierarchy = "created_at"
    actions = ["mark_played", "mark_rejected", "export_csv"]

    @admin.display(description="Vistas YT")
    def yt_views(self, obj):
        views = (obj.youtube_data or {}).get("views")
        return f"{views:,}".replace(",", ".") if views is not None else "—"

    @admin.display(description="Recomendación")
    def yt_moment(self, obj):
        return ((obj.youtube_data or {}).get("analysis") or {}).get("moment_label", "—")

    @admin.display(description="Pedida por")
    def requester(self, obj):
        return obj.guest.display_name

    def _set_status(self, request, queryset, status):
        queryset.update(status=status, status_changed_at=timezone.now(), handled_by=request.user)

    @admin.action(description="Marcar como sonada")
    def mark_played(self, request, queryset):
        self._set_status(request, queryset, SongRequest.Status.PLAYED)

    @admin.action(description="Marcar como no disponible")
    def mark_rejected(self, request, queryset):
        self._set_status(request, queryset, SongRequest.Status.REJECTED)

    @admin.action(description="Exportar a CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="solicitudes.csv"'
        response.write("﻿")  # BOM para que Excel abra bien las tildes
        writer = csv.writer(response)
        writer.writerow(["Fecha", "Discoteca", "Canción", "Artista", "Género", "Link", "Estado",
                         "Nombres", "Apellidos", "Alias", "Celular", "Correo", "IP", "Dispositivo"])
        for r in queryset.select_related("guest", "venue"):
            g = r.guest
            writer.writerow([
                timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"), r.venue.name, r.title, r.artist,
                r.get_genre_display(), r.reference_url, r.get_status_display(),
                g.first_name, g.last_name, g.alias, g.phone, g.email, r.client_ip or "", r.device_id,
            ])
        return response


@admin.register(SongRating)
class SongRatingAdmin(admin.ModelAdmin):
    list_display = ("song", "stars", "device_id", "client_ip", "updated_at")
    list_filter = ("stars", "song__venue")
    search_fields = ("song__title", "song__artist", "device_id", "client_ip")
    list_select_related = ("song",)
    readonly_fields = ("song", "device_id", "client_ip", "created_at", "updated_at")


@admin.register(LimitReset)
class LimitResetAdmin(admin.ModelAdmin):
    list_display = ("guest", "event", "songs_released", "reset_by", "created_at")
    list_filter = ("event",)
    search_fields = ("guest__email", "guest__first_name", "guest__alias")
    readonly_fields = ("guest", "event", "songs_released", "reset_by", "created_at")


@admin.register(ExperienceRating)
class ExperienceRatingAdmin(admin.ModelAdmin):
    list_display = ("guest", "venue", "venue_stars", "event", "event_stars", "dj", "dj_stars", "created_at")
    list_filter = ("venue", "event", "dj", "venue_stars", "event_stars", "dj_stars")
    search_fields = ("guest__email", "guest__first_name", "guest__alias")
    list_select_related = ("guest", "venue", "event", "dj")
    readonly_fields = ("guest", "venue", "event", "dj", "song", "created_at")
