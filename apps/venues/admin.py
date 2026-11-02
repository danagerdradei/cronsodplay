from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "is_active", "qr_link", "created_at")
    list_filter = ("is_active", "city")
    search_fields = ("name", "city")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="QR")
    def qr_link(self, obj):
        url = reverse("venues:qr_print", args=[obj.slug])
        return format_html('<a href="{}" target="_blank">Imprimir QR</a>', url)
