from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "venue", "code", "max_per_person", "is_open", "dj", "created_at", "share")
    list_filter = ("is_open", "venue")
    search_fields = ("name", "code")
    readonly_fields = ("code", "created_at", "closed_at")

    @admin.display(description="Link y QR")
    def share(self, obj):
        return format_html('<a href="{}">Abrir</a>', reverse("events:dj_detail", args=[obj.code]))
