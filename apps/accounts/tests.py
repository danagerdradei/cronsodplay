import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.events.models import Event
from apps.songs.models import Guest, SongRequest
from apps.venues.models import Venue

from .google import GoogleAuthError

GOOGLE_USER = {
    "sub": "1234567890", "email": "ana@gmail.com", "first_name": "Ana", "last_name": "Ruiz",
    "picture": "https://lh3.googleusercontent.com/a/foto",
}


@override_settings(GOOGLE_CLIENT_ID="test.apps.googleusercontent.com", GOOGLE_LOGIN_REQUIRED=True,
                   SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class GoogleLoginTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Cronso Club")
        self.request_url = reverse("songs:request_for_venue", args=[self.venue.slug])

    def google_login(self, user=GOOGLE_USER, next_url=None, client=None):
        client = client or self.client
        with patch("apps.accounts.views.verify_credential", return_value=dict(user)):
            return client.post(reverse("accounts:google_callback"),
                               json.dumps({"credential": "token", "next": next_url}), content_type="application/json")

    def post_song(self, title="Uno", **extra):
        data = {"venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop", "phone": "3001234567", **extra}
        return self.client.post(self.request_url, data)

    def test_request_pages_require_google_login(self):
        response = self.client.get(self.request_url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.request_url}", fetch_redirect_response=False)
        event = Event.objects.create(name="Viernes", venue=self.venue)
        self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 302)
        self.assertEqual(self.client.get(reverse("songs:my_requests")).status_code, 302)
        self.assertEqual(self.client.post(self.request_url, {}).status_code, 302)
        # La cola pública se puede ver sin sesión.
        self.assertEqual(self.client.get(reverse("songs:public_queue")).status_code, 200)

    def test_login_page_shows_google_button(self):
        response = self.client.get(reverse("accounts:login") + "?next=/pedir/")
        self.assertContains(response, 'data-client_id="test.apps.googleusercontent.com"')
        self.assertContains(response, "accounts.google.com/gsi/client")

    def test_google_login_creates_profile_and_redirects_to_next(self):
        response = self.google_login(next_url=self.request_url)
        self.assertEqual(response.json()["redirect"], self.request_url)
        guest = Guest.objects.get()
        self.assertEqual((guest.email, guest.first_name, guest.last_name, guest.google_sub),
                         ("ana@gmail.com", "Ana", "Ruiz", "1234567890"))
        self.assertEqual(self.client.get(self.request_url).status_code, 200)

    def test_unsafe_next_is_ignored(self):
        self.assertEqual(self.google_login(next_url="https://evil.example.com/").json()["redirect"], reverse("songs:request"))

    def test_invalid_google_token_is_rejected(self):
        with patch("apps.accounts.views.verify_credential", side_effect=GoogleAuthError("bad")):
            response = self.client.post(reverse("accounts:google_callback"), json.dumps({"credential": "x"}),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Guest.objects.exists())

    def test_form_uses_google_identity_and_only_asks_alias_and_phone(self):
        self.google_login()
        page = self.client.get(self.request_url)
        self.assertNotContains(page, 'name="first_name"')
        self.assertNotContains(page, 'name="email"')
        self.assertContains(page, "cuenta de Google")
        self.assertEqual(self.post_song(alias="Anita").status_code, 302)
        song = SongRequest.objects.get()
        self.assertEqual((song.guest.email, song.guest.alias, song.guest.phone), ("ana@gmail.com", "Anita", "3001234567"))

    def test_posted_names_or_email_cannot_override_google_identity(self):
        self.google_login()
        self.post_song(first_name="Otra", last_name="Persona", email="otra@x.com")
        self.assertEqual(Guest.objects.count(), 1)
        self.assertEqual(SongRequest.objects.get().guest.email, "ana@gmail.com")

    def test_existing_guest_is_linked_by_email(self):
        old = Guest.objects.create(email="ana@gmail.com", first_name="Ana María", last_name="Ruiz", phone="300", alias="Anita")
        self.google_login()
        old.refresh_from_db()
        self.assertEqual(old.google_sub, "1234567890")
        self.assertEqual(old.first_name, "Ana María")  # los nombres ya registrados no cambian
        self.assertEqual(Guest.objects.count(), 1)

    def test_limits_still_apply_per_event(self):
        self.google_login()
        event = Event.objects.create(name="Viernes", venue=self.venue, max_per_person=1)
        data = {"venue": self.venue.pk, "title": "Uno", "artist": "X", "genre": "pop", "phone": "3001234567",
                "venue_stars": 5, "event_stars": 4}
        self.assertEqual(self.client.post(event.get_absolute_url(), data).status_code, 302)
        self.assertContains(self.client.post(event.get_absolute_url(), {**data, "title": "Dos"}), "Gracias por tu buena energía")

    def test_rating_requires_login(self):
        guest = Guest.objects.create(email="b@x.com", first_name="B", last_name="C", phone="300")
        song = SongRequest.objects.create(guest=guest, venue=self.venue, title="T", artist="A", genre="pop")
        url = reverse("songs:rate_song", args=[song.pk])
        self.assertEqual(self.client.post(url, {"stars": 5}, content_type="application/json").status_code, 401)
        self.google_login()
        self.assertEqual(self.client.post(url, {"stars": 5}, content_type="application/json").status_code, 200)

    def test_my_requests_shows_own_songs_without_email_form(self):
        self.google_login()
        self.post_song("Mía")
        response = self.client.get(reverse("songs:my_requests"))
        self.assertContains(response, "Mía")
        self.assertNotContains(response, 'name="email"')

    def test_profile_and_logout(self):
        self.google_login()
        self.post_song("Uno", alias="Anita")
        event = Event.objects.create(name="Sábado", venue=self.venue, max_per_person=2)
        profile = self.client.get(reverse("accounts:profile"))
        self.assertContains(profile, "ana@gmail.com")
        self.assertContains(profile, "Sábado")
        self.assertContains(profile, "2 de 2 disponibles")
        # Alias fijo, celular editable
        self.client.post(reverse("accounts:profile"), {"alias": "Otro", "phone": "3109998877"})
        guest = Guest.objects.get()
        self.assertEqual((guest.alias, guest.phone), ("Anita", "3109998877"))
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(self.request_url).status_code, 302)
        self.assertTrue(event.pk)


@override_settings(GOOGLE_CLIENT_ID="", GOOGLE_LOGIN_REQUIRED=False)
class WithoutGoogleTests(TestCase):
    def test_app_works_without_google_configured(self):
        venue = Venue.objects.create(name="Club")
        self.assertEqual(self.client.get(reverse("songs:request_for_venue", args=[venue.slug])).status_code, 200)
        self.assertContains(self.client.get(reverse("accounts:login")), "aún no está configurado")
