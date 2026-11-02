from django.urls import path

from . import views

app_name = "venues"

urlpatterns = [
    path("<slug:slug>/", views.entry, name="entry"),
    path("<slug:slug>/qr.svg", views.qr_svg, name="qr_svg"),
    path("<slug:slug>/qr/", views.qr_print, name="qr_print"),
]
