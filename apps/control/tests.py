import os
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.dj.permissions import ADMIN_GROUP, DJ_GROUP
from apps.events.models import Event
from apps.songs.models import Guest, LimitReset, SongRequest
from apps.venues.models import Venue

STRONG = "Cr0nso-Pista-2026"


class ControlPanelTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        self.admin = User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.dj = User.objects.create_user("dj", password="pass12345")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.venue = Venue.objects.create(name="Cronso Club")
        self.guest = Guest.objects.create(email="ana@gmail.com", first_name="Ana", last_name="Ruiz",
                                          alias="Anita", phone="3001234567")
        SongRequest.objects.create(guest=self.guest, venue=self.venue, title="My Name Is", artist="Eminem", genre="hiphop")
        self.client.login(username="admin", password="pass12345")

    def test_only_admin_can_enter(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("control:dashboard")).status_code, 302)
        self.client.login(username="dj", password="pass12345")
        for name in ("control:dashboard", "control:staff", "control:people", "control:venues"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_admin_group_member_is_platform_admin(self):
        boss = User.objects.create_user("jefa", password="pass12345", is_staff=True)
        boss.groups.add(Group.objects.get(name=ADMIN_GROUP))
        self.client.login(username="jefa", password="pass12345")
        self.assertEqual(self.client.get(reverse("control:dashboard")).status_code, 200)

    def test_dashboard_shows_platform_numbers(self):
        response = self.client.get(reverse("control:dashboard"))
        self.assertContains(response, "Resumen de la plataforma")
        self.assertContains(response, "My Name Is")
        self.assertEqual(response.context["kpis"]["total"], 1)
        self.assertEqual(response.context["kpis"]["djs"], 1)

    def test_create_dj_and_admin_users(self):
        self.client.post(reverse("control:staff"), {"username": "dj_nuevo", "first_name": "DJ Nuevo", "role": "dj",
                                                    "password1": STRONG, "password2": STRONG})
        dj = User.objects.get(username="dj_nuevo")
        self.assertTrue(dj.groups.filter(name=DJ_GROUP).exists())
        self.assertFalse(dj.is_staff)
        self.assertTrue(dj.check_password(STRONG))
        self.client.post(reverse("control:staff"), {"username": "otra_admin", "role": "admin",
                                                    "password1": STRONG, "password2": STRONG})
        admin2 = User.objects.get(username="otra_admin")
        self.assertTrue(admin2.is_staff and admin2.groups.filter(name=ADMIN_GROUP).exists())

    def test_weak_or_mismatched_passwords_are_rejected(self):
        self.client.post(reverse("control:staff"), {"username": "x", "role": "dj", "password1": "123", "password2": "123"})
        self.assertFalse(User.objects.filter(username="x").exists())
        response = self.client.post(reverse("control:staff"),
                                    {"username": "y", "role": "dj", "password1": STRONG, "password2": "otra"})
        self.assertContains(response, "Las contraseñas no coinciden")

    def test_edit_role_deactivate_and_reset_password(self):
        self.client.post(reverse("control:staff_edit", args=[self.dj.pk]), {"first_name": "DJ Pro", "role": "admin"})
        self.dj.refresh_from_db()
        self.assertEqual((self.dj.first_name, self.dj.is_active, self.dj.is_staff), ("DJ Pro", False, True))
        self.client.post(reverse("control:staff_password", args=[self.dj.pk]), {"password1": STRONG, "password2": STRONG})
        self.dj.refresh_from_db()
        self.assertTrue(self.dj.check_password(STRONG))

    def test_admin_cannot_demote_or_deactivate_self(self):
        self.client.post(reverse("control:staff_edit", args=[self.admin.pk]), {"role": "dj", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_active)

    def test_people_list_shows_full_contact_and_search(self):
        response = self.client.get(reverse("control:people") + "?q=3001234")
        self.assertContains(response, "ana@gmail.com")
        self.assertContains(response, "3001234567")
        self.assertNotContains(self.client.get(reverse("control:people") + "?q=nadie"), "ana@gmail.com")

    def test_people_csv_export(self):
        response = self.client.get(reverse("control:people_export"))
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("ana@gmail.com", response.content.decode("utf-8"))

    def test_person_detail_reset_and_delete(self):
        event = Event.objects.create(name="Viernes", venue=self.venue, max_per_person=1)
        SongRequest.objects.create(guest=self.guest, venue=self.venue, event=event, title="Otra", artist="X", genre="pop")
        detail = self.client.get(reverse("control:person", args=[self.guest.pk]))
        self.assertContains(detail, "Viernes")
        self.assertContains(detail, "En el límite")
        self.client.post(reverse("control:person_reset", args=[self.guest.pk]), {"evento": event.code})
        self.assertEqual(LimitReset.objects.get().songs_released, 1)
        # Borrar exige escribir el correo exacto
        self.client.post(reverse("control:person_delete", args=[self.guest.pk]), {"confirmar": "otro@x.com"})
        self.assertTrue(Guest.objects.filter(pk=self.guest.pk).exists())
        self.client.post(reverse("control:person_delete", args=[self.guest.pk]), {"confirmar": "ana@gmail.com"})
        self.assertFalse(Guest.objects.filter(pk=self.guest.pk).exists())
        self.assertFalse(SongRequest.objects.exists())

    def test_venues_create_and_toggle(self):
        self.client.post(reverse("control:venues"), {"name": "La Terraza", "city": "Medellín"})
        venue = Venue.objects.get(name="La Terraza")
        self.client.post(reverse("control:venue_toggle", args=[venue.pk]))
        venue.refresh_from_db()
        self.assertFalse(venue.is_active)


class EventAdminTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        dj = User.objects.create_user("dj", password="pass12345")
        dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.venue = Venue.objects.create(name="Cronso Club")
        self.event = Event.objects.create(name="NaviRapas", venue=self.venue, max_per_person=2, allowed_genres=["hiphop"])
        self.other = Event.objects.create(name="Otro", venue=self.venue)
        self.ana = Guest.objects.create(email="ana@x.com", first_name="Ana", last_name="R", phone="300")
        self.beto = Guest.objects.create(email="beto@x.com", first_name="Beto", last_name="S", phone="301")
        for guest, title in ((self.ana, "Uno"), (self.ana, "Dos"), (self.beto, "Tres")):
            SongRequest.objects.create(guest=guest, venue=self.venue, event=self.event, title=title, artist="X", genre="hiphop")
        SongRequest.objects.create(guest=self.ana, venue=self.venue, event=self.other, title="Ajena", artist="X", genre="pop")
        SongRequest.objects.create(guest=self.ana, venue=self.venue, title="Sin evento", artist="X", genre="pop")
        self.client.login(username="admin", password="pass12345")

    def test_events_page_lists_events_and_is_admin_only(self):
        response = self.client.get(reverse("control:events"))
        self.assertContains(response, "Administrar eventos")
        self.assertContains(response, "NaviRapas")
        self.client.login(username="dj", password="pass12345")
        self.assertEqual(self.client.get(reverse("control:events")).status_code, 403)

    def test_reset_playlist_requires_code_and_only_touches_that_event(self):
        self.client.post(reverse("control:event_reset"), {"evento": self.event.code, "confirmar": "MAL"})
        self.assertEqual(SongRequest.objects.filter(event=self.event).count(), 3)
        response = self.client.post(reverse("control:event_reset"),
                                    {"evento": self.event.code, "confirmar": self.event.code.lower()}, follow=True)
        self.assertContains(response, "reiniciada")
        self.assertFalse(SongRequest.objects.filter(event=self.event).exists())
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())  # el evento se conserva
        self.assertEqual(SongRequest.objects.filter(title__in=["Ajena", "Sin evento"]).count(), 2)
        self.assertEqual(Guest.objects.count(), 2)  # las personas se conservan

    def test_after_reset_people_get_full_quota_again(self):
        from apps.songs.services import remaining_for_email
        self.assertEqual(remaining_for_email("ana@x.com", self.event), 0)
        self.client.post(reverse("control:event_reset"), {"evento": self.event.code, "confirmar": self.event.code})
        self.assertEqual(remaining_for_email("ana@x.com", self.event), 2)

    def test_admin_creates_and_edits_event(self):
        self.client.post(reverse("control:events"), {"name": "Sábado", "venue": self.venue.pk, "max_per_person": 4,
                                                     "allowed_genres": ["salsa"]})
        created = Event.objects.get(name="Sábado")
        self.assertEqual((created.max_per_person, created.allowed_genres), (4, ["salsa"]))
        edit_url = reverse("control:event_edit", args=[self.event.code])
        self.assertRegex(self.client.get(edit_url).content.decode(), r'<input[^>]*value="hiphop"[^>]*checked')
        self.client.post(edit_url, {"name": "NaviRapas 2", "venue": self.venue.pk, "max_per_person": 5,
                                    "allowed_genres": ["hiphop", "urbano"]})
        self.event.refresh_from_db()
        self.assertEqual((self.event.name, self.event.max_per_person, self.event.allowed_genres),
                         ("NaviRapas 2", 5, ["hiphop", "urbano"]))

    def test_toggle_and_delete_event(self):
        self.client.post(reverse("control:event_toggle", args=[self.event.code]))
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_open)
        delete_url = reverse("control:event_delete", args=[self.event.code])
        self.client.post(delete_url, {"confirmar": "NOPE"})
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.client.post(delete_url, {"confirmar": self.event.code})
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())
        self.assertEqual(SongRequest.objects.count(), 2)  # sus canciones se borraron; las demás no

    def test_toggle_ignores_external_redirect(self):
        response = self.client.post(reverse("control:event_toggle", args=[self.event.code]),
                                    {"volver": "https://evil.example.com/"})
        self.assertRedirects(response, reverse("control:events"))


class EnsureAdminCommandTests(TestCase):
    def setUp(self):
        call_command("setup_roles", verbosity=0)

    def test_creates_admin_if_missing_and_keeps_password_if_exists(self):
        env = {"DJANGO_SUPERUSER_USERNAME": "admin", "DJANGO_SUPERUSER_PASSWORD": "inicial-123"}
        with patch.dict(os.environ, env):
            call_command("ensure_admin", verbosity=0)
            admin = User.objects.get(username="admin")
            self.assertTrue(admin.is_superuser and admin.check_password("inicial-123"))
            admin.set_password("cambiada-456")
            admin.is_active = False
            admin.save()
            call_command("ensure_admin", verbosity=0)
        admin.refresh_from_db()
        self.assertTrue(admin.check_password("cambiada-456"))  # no pisa la contraseña cambiada
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.groups.filter(name=ADMIN_GROUP).exists())



class DjangoAdminToggleTests(TestCase):
    """/admin/ solo existe con DJANGO_ADMIN_ENABLED (local); en producción responde 404."""

    def _reload_urls(self):
        import importlib

        from django.urls import clear_url_caches

        import config.urls

        clear_url_caches()
        importlib.reload(config.urls)

    def setUp(self):
        call_command("setup_roles", verbosity=0)
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        self.client.login(username="admin", password="pass12345")

    def tearDown(self):
        self._reload_urls()  # vuelve a las URLs normales de las pruebas (admin activo)

    def test_admin_enabled_locally(self):
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertContains(self.client.get(reverse("control:dashboard")), "Avanzado")

    def test_admin_disabled_in_production(self):
        with self.settings(DJANGO_ADMIN_ENABLED=False):
            self._reload_urls()
            self.assertEqual(self.client.get("/admin/").status_code, 404)
            self.assertEqual(self.client.get("/admin/login/").status_code, 404)
            self.assertEqual(self.client.get("/admin/songs/guest/").status_code, 404)
            # El panel de control sigue funcionando, sin el enlace al administrador avanzado
            response = self.client.get(reverse("control:dashboard"))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Avanzado")
            self.assertEqual(self.client.get(reverse("control:events")).status_code, 200)
