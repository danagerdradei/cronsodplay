from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "dj"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("login/", RedirectView.as_view(pattern_name="staff_login", query_string=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("limites/", views.limits, name="limits"),
    path("limites/<int:guest_id>/restablecer/", views.reset_guest_limit, name="reset_limit"),
    path("api/requests/", views.api_requests, name="api_requests"),
    path("api/requests/<int:pk>/status/", views.api_update_status, name="api_update_status"),
]
