import io

import segno
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import cache_control

from .models import Venue


def entry(request, slug):
    """Destino del QR: lleva al formulario con la discoteca preseleccionada."""
    venue = get_object_or_404(Venue, slug=slug, is_active=True)
    return redirect("songs:request_for_venue", venue_slug=venue.slug)


@cache_control(max_age=86400)
def qr_svg(request, slug):
    """Imagen SVG del QR (ligera, escalable para impresión)."""
    venue = get_object_or_404(Venue, slug=slug)
    qr = segno.make(venue.public_url, error="h")
    # save(kind="svg") incluye xmlns: necesario para que el SVG funcione dentro de <img>.
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=10, border=2, dark="#000000", light="#ffffff", xmldecl=False)
    return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")


@staff_member_required
def qr_print(request, slug):
    """Página imprimible con el QR para poner en mesas / barra."""
    venue = get_object_or_404(Venue, slug=slug)
    return render(request, "venues/qr_print.html", {"venue": venue})
