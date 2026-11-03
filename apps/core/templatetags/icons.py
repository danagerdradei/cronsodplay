"""{% icon "nombre" %}: ícono de línea (Lucide) desde el sprite static/img/icons.svg."""
from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, extra_class="", label=""):
    """Hereda el color del texto (currentColor). Con `label` se anuncia a lectores de pantalla."""
    aria = format_html('role="img" aria-label="{}"', label) if label else format_html('aria-hidden="true"')
    return format_html(
        '<svg class="icon{}" {} focusable="false"><use href="{}#i-{}"></use></svg>',
        f" {extra_class}" if extra_class else "", aria, static("img/icons.svg"), name,
    )
