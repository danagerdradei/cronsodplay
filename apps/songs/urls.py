from django.urls import path

from . import api, views

app_name = "songs"

urlpatterns = [
    path("cola/", api.public_queue, name="public_queue"),
    path("link-preview/", api.link_preview, name="link_preview"),
    path("cola/<int:pk>/calificar/", api.rate_song, name="rate_song"),
    path("pedir/", views.request_song, name="request"),
    path("pedir/<slug:venue_slug>/", views.request_song, name="request_for_venue"),
    path("pedido/<int:pk>/", views.success, name="success"),
    path("mis-canciones/", views.my_requests, name="my_requests"),
    path("mis-canciones/salir/", views.forget_me, name="forget_me"),
]
