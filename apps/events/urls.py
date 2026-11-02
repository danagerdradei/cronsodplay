from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    # Público
    path("e/<str:code>/", views.entry, name="entry"),
    path("e/<str:code>/qr/", views.qr, name="qr"),
    # DJ
    path("dj/eventos/", views.dj_list, name="dj_list"),
    path("dj/eventos/<str:code>/", views.dj_detail, name="dj_detail"),
    path("dj/eventos/<str:code>/playlist/", views.dj_playlist, name="dj_playlist"),
    path("dj/eventos/<str:code>/estado/", views.dj_toggle, name="dj_toggle"),
    path("dj/eventos/<str:code>/imprimir/", views.dj_print, name="dj_print"),
]
