from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.dj.permissions import DJ_GROUP
from apps.dj.serializers import mask_email
from apps.songs.models import Guest, LimitReset, SongRequest
from apps.venues.models import Venue

from .models import CODE_ALPHABET, Event


def guest_data(email="ana@x.com", **extra):
    return {"first_name": "Ana", "last_name": "Ruiz", "alias": "", "phone": "3001234567", "email": email, **extra}


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=3, SONG_MAX_PER_IP=100, YOUTUBE_API_KEY="")
class EventTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="Cronso Club")
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.event = Event.objects.create(name="Viernes Urbano", venue=self.venue, max_per_person=2, dj=self.dj)

    def post(self, event, title, email="ana@x.com", client=None):
        data = {**guest_data(email), "venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop",
                "venue_stars": 5, "event_stars": 5, "dj_stars": 5}
        return (client or self.client).post(event.get_absolute_url(), data)

    def test_code_is_short_and_readable(self):
        self.assertEqual(len(self.event.code), 6)
        self.assertTrue(set(self.event.code) <= set(CODE_ALPHABET))
        self.assertTrue(self.event.public_url.endswith(f"/e/{self.event.code}/"))

    def test_event_link_shows_form_with_venue_and_event_limit(self):
        response = self.client.get(self.event.get_absolute_url())
        self.assertContains(response, "Viernes Urbano")
        self.assertContains(response, f'<input type="hidden" name="venue" value="{self.venue.pk}">', html=True)
        self.assertContains(response, "de 2</span>")
        self.assertContains(self.client.get(f"/e/{self.event.code.lower()}/"), "Viernes Urbano")  # sin mayúsculas

    def test_requests_are_attached_to_event_and_use_event_limit(self):
        self.assertEqual(self.post(self.event, "Uno").status_code, 302)
        self.assertEqual(self.post(self.event, "Dos").status_code, 302)
        self.assertContains(self.post(self.event, "Tres"), "Gracias por tu buena energía")
        self.assertEqual(SongRequest.objects.filter(event=self.event).count(), 2)

    def test_new_event_gives_a_fresh_quota_and_allows_same_song(self):
        self.post(self.event, "Uno")
        self.post(self.event, "Dos")
        saturday = Event.objects.create(name="Sábado", venue=self.venue, max_per_person=2)
        self.assertEqual(self.post(saturday, "Uno").status_code, 302)  # misma canción, otra noche

    def test_closed_event_does_not_accept_requests(self):
        self.event.is_open = False
        self.event.save()
        self.assertContains(self.client.get(self.event.get_absolute_url()), "ya terminó", status_code=410)
        self.assertEqual(self.post(self.event, "Uno").status_code, 410)
        self.assertFalse(SongRequest.objects.exists())

    def test_qr_png_and_svg(self):
        png = self.client.get(reverse("events:qr", args=[self.event.code]) + "?formato=png&descargar=1")
        self.assertEqual(png["Content-Type"], "image/png")
        self.assertIn("attachment", png["Content-Disposition"])
        svg = self.client.get(reverse("events:qr", args=[self.event.code]))
        self.assertEqual(svg["Content-Type"], "image/svg+xml")
        self.assertIn(b'xmlns="http://www.w3.org/2000/svg"', svg.content)  # sin esto no se ve en <img>
        venue_svg = self.client.get(reverse("venues:qr_svg", args=[self.venue.slug]))
        self.assertIn(b'xmlns="http://www.w3.org/2000/svg"', venue_svg.content)

    def test_dj_creates_event_and_gets_share_page(self):
        self.client.login(username="dj", password="pass12345")
        response = self.client.post(
            reverse("events:dj_list"), {"name": "Sábado Salsa", "venue": self.venue.pk, "max_per_person": 4}
        )
        event = Event.objects.get(name="Sábado Salsa")
        self.assertRedirects(response, reverse("events:dj_detail", args=[event.code]))
        detail = self.client.get(response["Location"])
        self.assertContains(detail, event.public_url)
        self.assertContains(detail, "wa.me")
        self.assertEqual(event.dj, self.dj)

    def test_dj_closes_event(self):
        self.client.login(username="dj", password="pass12345")
        self.client.post(reverse("events:dj_toggle", args=[self.event.code]))
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_open)

    def test_event_pages_require_dj(self):
        self.assertEqual(self.client.get(reverse("events:dj_list")).status_code, 302)
        self.assertEqual(self.client.post(reverse("events:dj_toggle", args=[self.event.code])).status_code, 302)

    def test_public_and_dj_queues_filter_by_event(self):
        self.post(self.event, "Del evento")
        self.client.post(reverse("songs:request_for_venue", args=[self.venue.slug]),
                         {**guest_data("b@x.com"), "venue": self.venue.pk, "title": "Sin evento", "artist": "X",
                          "genre": "pop"})
        public = self.client.get(reverse("songs:public_queue") + f"?event={self.event.code}").json()
        self.assertEqual([s["title"] for s in public["pending"]], ["Del evento"])
        self.assertEqual(public["event"]["name"], "Viernes Urbano")
        self.client.login(username="dj", password="pass12345")
        dj = self.client.get(reverse("dj:api_requests") + f"?event={self.event.code}").json()
        self.assertEqual([s["title"] for s in dj["results"]], ["Del evento"])
        self.assertEqual(dj["results"][0]["event"], "Viernes Urbano")


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=3, SONG_MAX_PER_IP=100, YOUTUBE_API_KEY="")
class LimitResetTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="Cronso Club")
        self.event = Event.objects.create(name="Viernes", venue=self.venue, max_per_person=2)
        self.dj = User.objects.create_user("dj", password="pass12345", first_name="DJ Demo")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.phone = self.client_class()  # dispositivo del asistente
        for title in ("Uno", "Dos"):
            self.phone.post(self.event.get_absolute_url(),
                            {**guest_data("elputres@hotmail.com", alias="Elputrefacto"), "venue": self.venue.pk,
                             "title": title, "artist": "X", "genre": "pop", "venue_stars": 5, "event_stars": 5, "dj_stars": 5})
        self.guest = Guest.objects.get(email="elputres@hotmail.com")
        self.client.login(username="dj", password="pass12345")

    def test_mask_email(self):
        self.assertEqual(mask_email("elputres@hotmail.com"), "el******@hotmail.com")
        self.assertEqual(mask_email("ab@x.com"), "a***@x.com")

    def test_lists_people_at_limit_with_masked_email(self):
        response = self.client.get(reverse("dj:limits") + f"?evento={self.event.code}")
        self.assertContains(response, "Elputrefacto")
        self.assertContains(response, "el******@hotmail.com")
        self.assertNotContains(response, "elputres@hotmail.com")
        self.assertNotContains(response, "3001234567")

    def test_lists_everyone_who_requested_with_people_at_limit_first(self):
        Guest.objects.create(email="sinpedir@gmail.com", first_name="Sin", last_name="Pedir", alias="Nadita", phone="1")
        self.client_class().post(self.event.get_absolute_url(),
                                 {**guest_data("may@gmail.com", alias="Mayita"), "venue": self.venue.pk,
                                  "title": "Solo una", "artist": "X", "genre": "pop"})
        page = self.client.get(reverse("dj:limits") + f"?evento={self.event.code}").content.decode()
        self.assertIn("Mayita", page)            # 1 de 2: también aparece
        self.assertNotIn("Nadita", page)         # se registró pero no ha pedido
        self.assertLess(page.index("Elputrefacto"), page.index("Mayita"))  # el del límite va primero
        self.assertIn("1 en el límite", page)

    def test_search_by_email_name_or_alias(self):
        for q in ("elputres@hotmail", "Ana", "putrefacto"):
            response = self.client.get(reverse("dj:limits") + f"?evento={self.event.code}&q={q}")
            self.assertContains(response, "Elputrefacto", msg_prefix=q)
        self.assertContains(self.client.get(reverse("dj:limits") + f"?evento={self.event.code}&q=nadie"),
                            "No se encontró")

    def test_reset_lets_the_person_request_again_and_keeps_songs_in_queue(self):
        response = self.client.post(reverse("dj:reset_limit", args=[self.guest.pk]), {"evento": self.event.code})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongRequest.objects.filter(guest=self.guest, status="pending").count(), 2)
        reset = LimitReset.objects.get()
        self.assertEqual((reset.songs_released, reset.reset_by, reset.event), (2, self.dj, self.event))
        # Mismo celular, mismo correo: ya puede pedir de nuevo (se liberó también el dispositivo).
        again = self.phone.post(self.event.get_absolute_url(),
                                {**guest_data("elputres@hotmail.com"), "venue": self.venue.pk,
                                 "title": "Tres", "artist": "X", "genre": "pop"})
        self.assertEqual(again.status_code, 302)

    def test_limits_page_requires_dj(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dj:limits")).status_code, 302)
        self.assertEqual(self.client.post(reverse("dj:reset_limit", args=[self.guest.pk])).status_code, 302)
        self.assertFalse(LimitReset.objects.exists())


class CreateVenueFromEventTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        Venue.objects.create(name="Cronso Club")
        dj = User.objects.create_user("dj", password="pass12345")
        dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.client.login(username="dj", password="pass12345")

    def create(self, **data):
        return self.client.post(reverse("events:dj_list"), {"name": "Noche", "max_per_person": 3, **data})

    def test_dj_creates_new_venue_with_event(self):
        response = self.create(new_venue="True", new_venue_name="  La Terraza   Club ", new_venue_city="Medellín")
        venue = Venue.objects.get(name="La Terraza Club")
        self.assertEqual((venue.city, venue.slug, venue.is_active), ("Medellín", "la-terraza-club", True))
        event = Event.objects.get()
        self.assertEqual(event.venue, venue)
        self.assertRedirects(response, reverse("events:dj_detail", args=[event.code]))

    def test_existing_name_is_reused_not_duplicated(self):
        self.create(new_venue="True", new_venue_name="cronso CLUB")
        self.assertEqual(Venue.objects.count(), 1)
        self.assertEqual(Event.objects.get().venue.name, "Cronso Club")

    def test_new_venue_requires_name_and_existing_requires_choice(self):
        self.assertContains(self.create(new_venue="True", new_venue_name=""), "Escribe el nombre de la discoteca")
        self.assertContains(self.create(), "Elige la discoteca o crea una nueva")
        self.assertFalse(Event.objects.exists())

    def test_similar_names_get_unique_slugs(self):
        # "Cronso-Club!" en el formulario se reutilizaría (mismo nombre normalizado); en el modelo
        # dos nombres distintos con el mismo slug reciben un sufijo.
        self.assertEqual(Venue.objects.create(name="Cronso-Club!").slug, "cronso-club-2")

    def test_form_shows_new_venue_fields_when_there_are_no_venues(self):
        Venue.objects.all().delete()
        response = self.client.get(reverse("events:dj_list"))
        self.assertContains(response, 'data-mode="new"')


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class EventGenreTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Cronso Club")
        self.event = Event.objects.create(name="Noche Latina", venue=self.venue,
                                          allowed_genres=["reggaeton", "salsa"])

    def post(self, genre, event=None, title="Uno"):
        data = {**guest_data(), "venue": self.venue.pk, "title": title, "artist": "X", "genre": genre}
        return self.client.post((event or self.event).get_absolute_url(), data)

    def test_form_shows_banner_and_only_allowed_genres(self):
        response = self.client.get(self.event.get_absolute_url())
        self.assertContains(response, "Esta noche el DJ toca")
        options = response.context["form"].fields["genre"].choices
        self.assertEqual([c for c, _ in options], ["", "reggaeton", "salsa"])

    def test_disallowed_genre_is_rejected_with_clear_message(self):
        response = self.post("rock")
        self.assertContains(response, "Este evento es solo de Reggaetón y Salsa")
        self.assertFalse(SongRequest.objects.exists())

    def test_allowed_genre_is_accepted(self):
        self.assertEqual(self.post("salsa").status_code, 302)

    def test_event_without_genres_accepts_any(self):
        open_event = Event.objects.create(name="Libre", venue=self.venue)
        self.assertEqual(self.post("rock", event=open_event).status_code, 302)

    def test_service_also_enforces_genres(self):
        from apps.songs.services import GenreNotAllowed, register_song_request
        with self.assertRaises(GenreNotAllowed):
            register_song_request(
                guest_data=guest_data(), event=self.event,
                song_data={"venue": self.venue, "title": "Y", "artist": "X", "genre": "pop", "reference_url": ""},
            )

    def test_dj_creates_event_with_genres(self):
        call_command("setup_roles", verbosity=0)
        dj = User.objects.create_user("dj", password="pass12345")
        dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.client.login(username="dj", password="pass12345")
        self.client.post(reverse("events:dj_list"), {
            "name": "Electro", "venue": self.venue.pk, "max_per_person": 3,
            "allowed_genres": ["electronica", "house"],
        })
        event = Event.objects.get(name="Electro")
        self.assertEqual(event.allowed_genres, ["electronica", "house"])
        self.assertContains(self.client.get(reverse("events:dj_detail", args=[event.code])), "House / Tech House")


class EventViewsByRoleTests(TestCase):
    """El Admin administra todos los eventos en /control/eventos/; el DJ solo ve y comparte los suyos."""

    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="Cronso Club")
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.other_dj = User.objects.create_user("otro", password="pass12345")
        for user in (self.dj, self.other_dj):
            user.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.mine = Event.objects.create(name="Mi Noche", venue=self.venue, dj=self.dj)
        self.theirs = Event.objects.create(name="Noche Ajena", venue=self.venue, dj=self.other_dj)

    def test_admin_is_sent_to_control_events(self):
        self.client.login(username="admin", password="pass12345")
        self.assertRedirects(self.client.get(reverse("events:dj_list")), reverse("control:events"))
        # El Admin sí puede abrir el link/QR de cualquier evento
        self.assertEqual(self.client.get(reverse("events:dj_detail", args=[self.theirs.code])).status_code, 200)

    def test_dj_sees_only_own_events(self):
        self.client.login(username="dj", password="pass12345")
        response = self.client.get(reverse("events:dj_list"))
        self.assertContains(response, "Mi Noche")
        self.assertNotContains(response, "Noche Ajena")
        self.assertContains(response, "Mis eventos")

    def test_dj_cannot_manage_other_djs_events(self):
        self.client.login(username="dj", password="pass12345")
        self.assertEqual(self.client.get(reverse("events:dj_detail", args=[self.theirs.code])).status_code, 404)
        self.assertEqual(self.client.post(reverse("events:dj_toggle", args=[self.theirs.code])).status_code, 404)
        self.theirs.refresh_from_db()
        self.assertTrue(self.theirs.is_open)
        self.assertEqual(self.client.get(reverse("events:dj_print", args=[self.theirs.code])).status_code, 404)

    def test_dj_cannot_use_admin_event_tools(self):
        self.client.login(username="dj", password="pass12345")
        self.assertEqual(self.client.get(reverse("control:events")).status_code, 403)
        self.assertEqual(self.client.get(reverse("control:event_edit", args=[self.mine.code])).status_code, 403)
        response = self.client.post(reverse("control:event_reset"), {"evento": self.mine.code, "confirmar": self.mine.code})
        self.assertEqual(response.status_code, 403)



class EventPlaylistPageTests(TestCase):
    """Cada evento tiene su página de playlist: la ve el DJ dueño y el Admin."""

    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="ClorofilaTaller")
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.other = User.objects.create_user("otro", password="pass12345")
        for user in (self.dj, self.other):
            user.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.event = Event.objects.create(name="NaviRapas", venue=self.venue, dj=self.dj, allowed_genres=["hiphop"])
        self.url = reverse("events:dj_playlist", args=[self.event.code])

    def test_owner_dj_sees_the_event_playlist(self):
        self.client.login(username="dj", password="pass12345")
        response = self.client.get(self.url)
        self.assertContains(response, "Playlist del evento")
        self.assertContains(response, "NaviRapas")
        self.assertContains(response, f'data-fixed-event="{self.event.code}"')
        self.assertNotContains(response, 'id="event-filter"')  # sin selectores: el evento es fijo
        self.assertNotContains(response, "#reset-form\">")       # herramientas del Admin ocultas

    def test_other_dj_cannot_open_it(self):
        self.client.login(username="otro", password="pass12345")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_admin_sees_it_with_admin_tools(self):
        self.client.login(username="admin", password="pass12345")
        response = self.client.get(self.url)
        self.assertContains(response, "NaviRapas")
        self.assertContains(response, "#reset-form\">")
        self.assertContains(response, reverse("control:event_edit", args=[self.event.code]))

    def test_requires_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_playlist_links_everywhere(self):
        self.client.login(username="dj", password="pass12345")
        self.assertContains(self.client.get(reverse("events:dj_list")), self.url)
        self.assertContains(self.client.get(reverse("events:dj_detail", args=[self.event.code])), self.url)
        self.client.login(username="admin", password="pass12345")
        self.assertContains(self.client.get(reverse("control:events")), self.url)
        self.assertContains(self.client.get(reverse("control:event_edit", args=[self.event.code])), self.url)



@override_settings(GOOGLE_CLIENT_ID="test.apps.googleusercontent.com", GOOGLE_LOGIN_REQUIRED=True, YOUTUBE_API_KEY="")
class StaffPreviewAndDeleteTests(TestCase):
    """El DJ/Admin ve el link del evento sin Google (solo lectura) y puede eliminar canciones de su cola."""

    def setUp(self):
        from apps.songs.models import Guest, SongRequest
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="ClorofilaTaller")
        self.dj = User.objects.create_user("djcronso", password="pass12345")
        self.other = User.objects.create_user("otro", password="pass12345")
        for u in (self.dj, self.other):
            u.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.event = Event.objects.create(name="Halloweens2", venue=self.venue, dj=self.dj, max_per_person=3)
        guest = Guest.objects.create(email="g@gmail.com", first_name="Gera", last_name="V", phone="300")
        self.song = SongRequest.objects.create(guest=guest, venue=self.venue, event=self.event, title="Rompe",
                                               artist="Daddy Yankee", genre="reggaeton")
        self.guest = guest

    def test_public_visitor_still_needs_google(self):
        self.assertEqual(self.client.get(self.event.get_absolute_url()).status_code, 302)

    def test_dj_sees_public_view_without_google(self):
        self.client.login(username="djcronso", password="pass12345")
        response = self.client.get(self.event.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vista de público")
        self.assertContains(response, "fieldset disabled")
        self.assertContains(response, reverse("events:dj_playlist", args=[self.event.code]))

    def test_dj_cannot_submit_songs_from_preview(self):
        from apps.songs.models import SongRequest
        self.client.login(username="djcronso", password="pass12345")
        response = self.client.post(self.event.get_absolute_url(), {"title": "X", "artist": "Y", "genre": "pop",
                                                                    "venue": self.venue.pk, "phone": "300"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongRequest.objects.count(), 1)

    def test_owner_dj_deletes_song_and_quota_is_freed(self):
        from apps.songs.models import SongRequest
        from apps.songs.services import remaining_for_email
        self.client.login(username="djcronso", password="pass12345")
        self.assertEqual(remaining_for_email("g@gmail.com", self.event), 2)
        response = self.client.post(reverse("dj:api_delete_request", args=[self.song.pk]))
        self.assertEqual(response.json(), {"deleted": self.song.pk})
        self.assertFalse(SongRequest.objects.exists())
        self.assertEqual(remaining_for_email("g@gmail.com", self.event), 3)

    def test_other_dj_cannot_delete_but_admin_can(self):
        from apps.songs.models import SongRequest
        self.client.login(username="otro", password="pass12345")
        self.assertEqual(self.client.post(reverse("dj:api_delete_request", args=[self.song.pk])).status_code, 403)
        self.assertTrue(SongRequest.objects.exists())
        self.client.login(username="admin", password="pass12345")
        self.assertEqual(self.client.post(reverse("dj:api_delete_request", args=[self.song.pk])).status_code, 200)
        self.assertFalse(SongRequest.objects.exists())

    def test_delete_requires_staff_and_post(self):
        self.assertEqual(self.client.post(reverse("dj:api_delete_request", args=[self.song.pk])).status_code, 401)
        self.client.login(username="djcronso", password="pass12345")
        self.assertEqual(self.client.get(reverse("dj:api_delete_request", args=[self.song.pk])).status_code, 405)

    def test_playlist_has_delete_button(self):
        self.client.login(username="djcronso", password="pass12345")
        self.assertContains(self.client.get(reverse("events:dj_playlist", args=[self.event.code])), "data-delete")



@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class PauseFinalizeHistoryTests(TestCase):
    """El DJ pausa/reanuda los pedidos y finaliza el evento, que queda con su playlist en el historial."""

    def setUp(self):
        from apps.songs.models import Guest, SongRating, SongRequest
        call_command("setup_roles", verbosity=0)
        self.venue = Venue.objects.create(name="La Casa del Hip Hop")
        self.dj = User.objects.create_user("djcronso", password="pass12345", first_name="DJ Cronso")
        self.other = User.objects.create_user("otro", password="pass12345")
        for u in (self.dj, self.other):
            u.groups.add(Group.objects.get(name=DJ_GROUP))
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.event = Event.objects.create(name="Houseofhiphoplandia", venue=self.venue, dj=self.dj)
        guest = Guest.objects.create(email="lalo@gmail.com", first_name="Lalo", last_name="R", alias="Lalondra", phone="300")
        self.song = SongRequest.objects.create(guest=guest, venue=self.venue, event=self.event, title="Buffalo Soldier",
                                               artist="Bob Marley", genre="reggae", status="played",
                                               reference_url="https://youtu.be/S5FCdx7Dn0o")
        SongRating.objects.create(song=self.song, device_id="d1", stars=4)
        self.client.login(username="djcronso", password="pass12345")

    def post_song(self, title):
        data = {**guest_data("nuevo@gmail.com"), "venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop"}
        return self.client_class().post(self.event.get_absolute_url(), data)

    def test_pause_shows_notice_and_blocks_requests(self):
        from apps.songs.models import SongRequest
        self.client.post(reverse("events:dj_pause", args=[self.event.code]))
        self.event.refresh_from_db()
        self.assertFalse(self.event.accepting_requests)
        self.assertEqual(self.event.status_key, "paused")
        page = self.client_class().get(self.event.get_absolute_url())
        self.assertContains(page, "El DJ pausó los pedidos")
        self.assertContains(page, 'id="public-queue"')  # la cola sigue visible
        self.post_song("Durante la pausa")
        self.assertFalse(SongRequest.objects.filter(title="Durante la pausa").exists())

    def test_resume_accepts_requests_again(self):
        from apps.songs.models import SongRequest
        self.client.post(reverse("events:dj_pause", args=[self.event.code]))
        self.client.post(reverse("events:dj_pause", args=[self.event.code]))
        self.event.refresh_from_db()
        self.assertTrue(self.event.accepting_requests)
        self.assertEqual(self.post_song("Ya reanudado").status_code, 302)
        self.assertTrue(SongRequest.objects.filter(title="Ya reanudado").exists())

    def test_finalize_requires_code_and_saves_snapshot(self):
        url = reverse("events:dj_finalize", args=[self.event.code])
        self.client.post(url, {"confirmar": "MAL"})
        self.event.refresh_from_db()
        self.assertIsNone(self.event.finalized_at)
        response = self.client.post(url, {"confirmar": self.event.code.lower()})
        self.assertRedirects(response, reverse("events:dj_history_detail", args=[self.event.code]))
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_finalized)
        self.assertFalse(self.event.is_open)
        snap = self.event.playlist_snapshot
        self.assertEqual(snap["summary"]["total"], 1)
        self.assertEqual(snap["summary"]["played"], 1)
        song = snap["songs"][0]
        self.assertEqual((song["title"], song["requester"], song["requester_email"]), ("Buffalo Soldier", "Lalondra", "lalo@gmail.com"))
        self.assertEqual((song["rating_avg"], song["rating_n"]), (4.0, 1))

    def test_finalized_event_is_closed_for_good(self):
        from apps.songs.models import SongRequest
        self.client.post(reverse("events:dj_finalize", args=[self.event.code]), {"confirmar": self.event.code})
        self.assertEqual(self.client_class().get(self.event.get_absolute_url()).status_code, 410)
        self.client.post(reverse("events:dj_toggle", args=[self.event.code]))  # intentar reabrir
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_open)
        self.assertNotContains(self.client.get(reverse("events:dj_list")), 'class="event-card')  # ya no está en "Mis eventos"
        # El historial no cambia aunque después se borren las canciones
        SongRequest.objects.all().delete()
        self.assertContains(self.client.get(reverse("events:dj_history_detail", args=[self.event.code])), "Buffalo Soldier")

    def test_history_list_detail_and_csv(self):
        self.client.post(reverse("events:dj_finalize", args=[self.event.code]), {"confirmar": self.event.code})
        self.assertContains(self.client.get(reverse("events:dj_history")), "Houseofhiphoplandia")
        detail = self.client.get(reverse("events:dj_history_detail", args=[self.event.code]))
        self.assertContains(detail, "lalo@gmail.com")
        csv_response = self.client.get(reverse("events:dj_history_csv", args=[self.event.code]))
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Buffalo Soldier", csv_response.content.decode("utf-8"))

    def test_history_is_private_to_owner_and_admin(self):
        self.client.post(reverse("events:dj_finalize", args=[self.event.code]), {"confirmar": self.event.code})
        self.client.login(username="otro", password="pass12345")
        self.assertEqual(self.client.get(reverse("events:dj_history_detail", args=[self.event.code])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("events:dj_history")), "Houseofhiphoplandia")
        self.client.login(username="admin", password="pass12345")
        self.assertEqual(self.client.get(reverse("events:dj_history_detail", args=[self.event.code])).status_code, 200)

    def test_other_dj_cannot_pause_or_finalize(self):
        self.client.login(username="otro", password="pass12345")
        self.assertEqual(self.client.post(reverse("events:dj_pause", args=[self.event.code])).status_code, 404)
        self.assertEqual(self.client.post(reverse("events:dj_finalize", args=[self.event.code]),
                                          {"confirmar": self.event.code}).status_code, 404)



@override_settings(REQUESTS_REQUIRE_EVENT=True, SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0,
                   YOUTUBE_API_KEY="")
class RequestsRequireEventTests(TestCase):
    """Sin evento no se piden canciones: "Pedir" muestra los eventos abiertos y el QR del local lleva al evento."""

    def setUp(self):
        self.casa = Venue.objects.create(name="La Casa del Hip Hop", city="Bello")
        self.cloro = Venue.objects.create(name="ClorofilaTaller")
        self.hiphop = Event.objects.create(name="Houseofhiphoplandia", venue=self.casa)
        self.cloro_a = Event.objects.create(name="Viernes", venue=self.cloro)
        self.cloro_b = Event.objects.create(name="Sábado", venue=self.cloro, accepting_requests=False)
        Event.objects.create(name="Cerrado", venue=self.cloro, is_open=False)

    def test_pedir_lists_open_events_by_venue(self):
        response = self.client.get(reverse("songs:request"))
        self.assertContains(response, "¿Dónde estás esta noche?")
        for name in ("Houseofhiphoplandia", "Viernes", "Sábado", "La Casa del Hip Hop", "ClorofilaTaller"):
            self.assertContains(response, name)
        self.assertNotContains(response, "Cerrado</strong>")
        self.assertContains(response, self.hiphop.get_absolute_url())
        self.assertNotContains(response, 'name="title"')  # no hay formulario suelto

    def test_venue_with_one_event_goes_straight_to_it(self):
        response = self.client.get(reverse("songs:request_for_venue", args=[self.casa.slug]))
        self.assertRedirects(response, self.hiphop.get_absolute_url(), fetch_redirect_response=False)

    def test_venue_with_several_events_lets_choose(self):
        response = self.client.get(reverse("songs:request_for_venue", args=[self.cloro.slug]))
        self.assertContains(response, "Viernes")
        self.assertContains(response, "Pausado")
        self.assertNotContains(response, "Houseofhiphoplandia")

    def test_venue_without_events_shows_notice(self):
        empty = Venue.objects.create(name="Bar Vacío")
        self.assertContains(self.client.get(reverse("songs:request_for_venue", args=[empty.slug])),
                            "Ahora no hay eventos abiertos")

    def test_cannot_request_without_event(self):
        from apps.songs.models import SongRequest
        data = {**guest_data(), "venue": self.cloro.pk, "title": "Suelta", "artist": "X", "genre": "pop"}
        self.client.post(reverse("songs:request_for_venue", args=[self.cloro.slug]), data)
        self.client.post(reverse("songs:request"), data)
        self.assertFalse(SongRequest.objects.exists())

    def test_quota_cannot_be_bypassed_outside_the_event(self):
        from apps.songs.models import SongRequest
        url = self.hiphop.get_absolute_url()
        for title in ("Uno", "Dos"):
            self.client.post(url, {**guest_data(), "venue": self.casa.pk, "title": title, "artist": "X", "genre": "pop"})
        self.client.post(url, {**guest_data(), "venue": self.casa.pk, "title": "Tres", "artist": "X", "genre": "pop",
                               "venue_stars": 5, "event_stars": 5})
        # Ya usó sus 3 en el evento: por "Pedir" no hay otro cupo
        self.client.post(reverse("songs:request"), {**guest_data(), "venue": self.casa.pk, "title": "Cuatro",
                                                     "artist": "X", "genre": "pop"})
        self.assertEqual(SongRequest.objects.count(), 3)
        self.assertContains(self.client.post(url, {**guest_data(), "venue": self.casa.pk, "title": "Cinco",
                                                    "artist": "X", "genre": "pop"}), "Gracias por tu buena energía")

    def test_venue_qr_leads_to_its_event(self):
        response = self.client.get(reverse("venues:entry", args=[self.casa.slug]), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], self.hiphop.get_absolute_url())


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class NoRepeatedSongsPerEventTests(TestCase):
    """En un evento cada canción se pide una sola vez, la pida quien la pida."""

    def setUp(self):
        self.venue = Venue.objects.create(name="La Casa del Hip Hop")
        self.event = Event.objects.create(name="Houseofhiphoplandia", venue=self.venue)
        self.post("may@gmail.com", "La Kelly", "El cartel de santa", "https://youtu.be/AAAAAAAAAAA")

    def post(self, email, title, artist, link="", event=None):
        data = {**guest_data(email), "venue": self.venue.pk, "title": title, "artist": artist,
                "genre": "hiphop", "reference_url": link}
        return self.client_class().post((event or self.event).get_absolute_url(), data)

    def test_variations_of_the_same_song_are_blocked_for_anyone(self):
        for email, title, artist in [("may@gmail.com", "La kelly", "Cartel de santa"),
                                     ("otro@gmail.com", "LA KELLY", "Cártel de Santa"),
                                     ("otro2@gmail.com", "Cartel de Santa", "La Kelly")]:
            response = self.post(email, title, artist)
            self.assertContains(response, "ya está en la cola de esta noche", msg_prefix=f"{title}/{artist}")
        self.assertEqual(SongRequest.objects.count(), 1)

    def test_same_video_with_other_name_is_blocked(self):
        self.assertContains(self.post("otro@gmail.com", "Shorty Party", "Kelly", "https://www.youtube.com/watch?v=AAAAAAAAAAA"),
                            "ya está en la cola de esta noche")
        self.assertEqual(SongRequest.objects.count(), 1)

    def test_played_song_cannot_be_requested_again(self):
        SongRequest.objects.update(status=SongRequest.Status.PLAYED)
        self.assertContains(self.post("otro@gmail.com", "La Kelly", "Cartel de Santa"), "ya sonó esta noche")

    def test_other_songs_and_other_events_are_allowed(self):
        self.assertEqual(self.post("otro@gmail.com", "Shorty Party", "Cartel de Santa").status_code, 302)
        other = Event.objects.create(name="Otra noche", venue=self.venue)
        self.assertEqual(self.post("otro2@gmail.com", "La Kelly", "Cartel de Santa", event=other).status_code, 302)
        self.assertEqual(SongRequest.objects.count(), 3)

    def test_deleted_song_can_be_requested_again(self):
        SongRequest.objects.all().delete()
        self.assertEqual(self.post("otro@gmail.com", "La Kelly", "Cartel de Santa").status_code, 302)


@override_settings(REQUESTS_REQUIRE_EVENT=True, SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0,
                   YOUTUBE_API_KEY="")
class MyRequestsQuotaTests(TestCase):
    """"Mis canciones" muestra el cupo real de cada evento abierto, no un número genérico."""

    def setUp(self):
        self.venue = Venue.objects.create(name="La Casa del Hip Hop")
        self.event = Event.objects.create(name="Houseofhiphoplandia", venue=self.venue, max_per_person=3)
        self.full = Event.objects.create(name="Viernes", venue=self.venue, max_per_person=1)
        for event, title in ((self.event, "Uno"), (self.event, "Dos"), (self.full, "Tres")):
            self.client.post(event.get_absolute_url(), {**guest_data(), "venue": self.venue.pk, "title": title,
                                                         "artist": "X", "genre": "pop", "venue_stars": 5, "event_stars": 5})

    def test_shows_remaining_per_event(self):
        page = self.client.get(reverse("songs:my_requests"))
        self.assertContains(page, "Te quedan 1 de 3")
        self.assertContains(page, "Ya usaste tus 1")
        self.assertNotContains(page, "Pedir canción (")
        self.assertContains(page, self.event.get_absolute_url())

    def test_finalized_events_are_not_listed(self):
        from django.utils import timezone
        Event.objects.filter(pk=self.full.pk).update(finalized_at=timezone.now(), is_open=False)
        self.assertNotContains(self.client.get(reverse("songs:my_requests")), "Ya usaste tus 1")
