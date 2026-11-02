import json

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.songs.models import Guest, SongRequest
from apps.venues.models import Venue

from .permissions import DJ_GROUP


class DjApiTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="Club")
        guest = Guest.objects.create(
            email="a@b.com", first_name="Ana", last_name="Ruiz", alias="Anita", phone="3001234567"
        )
        self.song = SongRequest.objects.create(guest=guest, venue=self.venue, title="Uno", artist="X", genre="pop")
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.get(reverse("dj:api_requests")).status_code, 401)

    def test_regular_user_gets_403(self):
        User.objects.create_user("x", password="pass12345")
        self.client.login(username="x", password="pass12345")
        self.assertEqual(self.client.get(reverse("dj:api_requests")).status_code, 403)

    def test_dj_sees_queue_without_private_data(self):
        self.client.login(username="dj", password="pass12345")
        data = self.client.get(reverse("dj:api_requests")).json()
        self.assertEqual(data["counts"]["pending"], 1)
        item = data["results"][0]
        self.assertEqual(item["requester"], "Anita")
        self.assertNotIn("email", json.dumps(item))
        self.assertNotIn("3001234567", json.dumps(item))

    def test_dj_marks_song_as_played(self):
        self.client.login(username="dj", password="pass12345")
        url = reverse("dj:api_update_status", args=[self.song.pk])
        response = self.client.post(url, {"status": "played"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.song.refresh_from_db()
        self.assertEqual(self.song.status, SongRequest.Status.PLAYED)
        self.assertEqual(self.song.handled_by, self.dj)

    def test_dj_cannot_enter_django_admin(self):
        self.client.login(username="dj", password="pass12345")
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)


class StaffLoginTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        User.objects.create_user("nadie", password="pass12345")

    def login(self, username, next_url=None):
        data = {"username": username, "password": "pass12345"}
        if next_url:
            data["next"] = next_url
        return self.client.post(reverse("staff_login"), data)

    def test_single_login_page_with_logo(self):
        response = self.client.get(reverse("staff_login"))
        self.assertContains(response, "Acceso DJ · Admin")
        self.assertContains(response, "logo-cronso")

    def test_dj_goes_to_panel_and_admin_to_admin(self):
        self.assertRedirects(self.login("dj"), reverse("dj:panel"))
        self.client.logout()
        self.assertRedirects(self.login("admin"), reverse("control:dashboard"))

    def test_next_is_respected(self):
        self.assertRedirects(self.login("admin", reverse("dj:limits")), reverse("dj:limits"))

    def test_user_without_role_cannot_enter(self):
        response = self.login("nadie")
        self.assertContains(response, "no tiene perfil de DJ ni de Admin")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_message(self):
        response = self.client.post(reverse("staff_login"), {"username": "dj", "password": "mala"})
        self.assertContains(response, "Usuario o contraseña incorrectos")

    def test_old_urls_redirect_to_single_login(self):
        self.assertRedirects(self.client.get("/dj/login/?next=/dj/"), "/acceso/?next=/dj/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/admin/login/?next=/admin/"), "/acceso/?next=/admin/",
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/admin/"), "/admin/login/?next=/admin/", fetch_redirect_response=False)



class StaffLoginModalTests(TestCase):
    """Botón "Acceso DJ" con modal en las páginas públicas; las cuentas solo las crea el Admin."""

    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")

    def test_public_pages_show_button_and_modal(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "data-open-staff-login")
        self.assertContains(response, 'id="staff-login-dialog"')
        self.assertContains(response, f'action="{reverse("staff_login")}"')
        self.assertContains(response, "solo las crea el Admin")

    def test_modal_login_works_like_the_access_page(self):
        response = self.client.post(reverse("staff_login"), {"username": "dj", "password": "pass12345"})
        self.assertRedirects(response, reverse("dj:panel"))

    def test_logged_in_staff_see_their_panel_link_instead(self):
        self.client.login(username="dj", password="pass12345")
        home = self.client.get(reverse("core:home"))
        self.assertNotContains(home, 'id="staff-login-dialog"')
        self.assertContains(home, "Mi panel")
        self.client.login(username="admin", password="pass12345")
        self.assertContains(self.client.get(reverse("core:home")), reverse("control:dashboard"))

    def test_there_is_no_public_signup(self):
        from django.urls import NoReverseMatch
        for name in ("signup", "register", "registro", "dj:signup", "dj:register"):
            with self.assertRaises(NoReverseMatch):
                reverse(name)
        for path in ("/registro/", "/signup/", "/dj/registro/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)



class StaffLoginModalAjaxTests(TestCase):
    """El modal muestra el error ahí mismo y un formulario viejo (CSRF) ve una página amable."""

    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))

    def test_wrong_password_returns_error_for_the_modal(self):
        response = self.client.post(reverse("staff_login"), {"username": "dj", "password": "mala"}, **self.AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Usuario o contraseña incorrectos.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_empty_fields_return_error_for_the_modal(self):
        response = self.client.post(reverse("staff_login"), {"username": "", "password": ""}, **self.AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertIn("usuario", response.json()["error"].lower())

    def test_right_password_returns_redirect_for_the_modal(self):
        response = self.client.post(reverse("staff_login"), {"username": "dj", "password": "pass12345"}, **self.AJAX)
        self.assertEqual(response.json(), {"redirect": reverse("dj:panel")})
        self.assertIn("_auth_user_id", self.client.session)

    def test_access_page_without_ajax_still_shows_message(self):
        response = self.client.post(reverse("staff_login"), {"username": "dj", "password": "mala"})
        self.assertContains(response, "Usuario o contraseña incorrectos")

    def test_access_page_does_not_duplicate_the_modal(self):
        response = self.client.get(reverse("staff_login"))
        self.assertNotContains(response, 'id="staff-login-dialog"')

    def test_stale_csrf_token_shows_friendly_page(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.get(reverse("core:home"))  # recibe una cookie CSRF
        response = strict.post(reverse("staff_login"),
                               {"username": "dj", "password": "mala", "csrfmiddlewaretoken": "x" * 64})
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Tu formulario expiró", status_code=403)
        self.assertContains(response, "Volver a intentarlo", status_code=403)

    def test_csrf_cookie_value_is_accepted_as_token(self):
        """El modal envía el valor de la cookie csrftoken: Django debe aceptarlo."""
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.get(reverse("core:home"))
        token = strict.cookies["csrftoken"].value
        response = strict.post(reverse("staff_login"), {"username": "dj", "password": "pass12345",
                               "csrfmiddlewaretoken": token}, HTTP_X_CSRFTOKEN=token, **self.AJAX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], reverse("dj:panel"))
