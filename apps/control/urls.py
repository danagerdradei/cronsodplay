from django.urls import path

from . import views

app_name = "control"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("usuarios/", views.staff_list, name="staff"),
    path("usuarios/<int:user_id>/", views.staff_edit, name="staff_edit"),
    path("usuarios/<int:user_id>/contrasena/", views.staff_password, name="staff_password"),
    path("personas/", views.people_list, name="people"),
    path("personas/exportar/", views.people_export, name="people_export"),
    path("personas/<int:guest_id>/", views.person_detail, name="person"),
    path("personas/<int:guest_id>/restablecer/", views.person_reset, name="person_reset"),
    path("personas/<int:guest_id>/eliminar/", views.person_delete, name="person_delete"),
    path("eventos/", views.events, name="events"),
    path("eventos/reiniciar/", views.event_reset, name="event_reset"),
    path("eventos/<str:code>/", views.event_edit, name="event_edit"),
    path("eventos/<str:code>/estado/", views.event_toggle, name="event_toggle"),
    path("eventos/<str:code>/eliminar/", views.event_delete, name="event_delete"),
    path("discotecas/", views.venues, name="venues"),
    path("discotecas/<int:venue_id>/estado/", views.venue_toggle, name="venue_toggle"),
]
