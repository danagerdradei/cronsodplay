from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("entrar/", views.login_view, name="login"),
    path("auth/google/", views.google_callback, name="google_callback"),
    path("salir/", views.logout_view, name="logout"),
    path("perfil/", views.profile, name="profile"),
]
