import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.net import get_client_ip
from apps.venues.models import Venue

from . import youtube
from .analysis import analyze
from .models import ExperienceRating, Guest, SongRating, SongRequest
from .services import DuplicateSong, LimitReached, register_song_request
from .thumbnails import fetch_thumbnail, youtube_video_id


STARS = {"venue_stars": 5, "event_stars": 5, "dj_stars": 5}


def guest_data(email="ana@example.com"):
    return {"first_name": "Ana", "last_name": "Ruiz", "alias": "", "phone": "3001234567", "email": email}


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_LIMIT_WINDOW_HOURS=0)
class RegisterSongRequestTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club Prueba")

    def song(self, title, artist="Artista"):
        return {"venue": self.venue, "title": title, "artist": artist, "genre": "salsa", "reference_url": ""}

    def test_allows_up_to_three_songs_per_email(self):
        for t in ("Uno", "Dos", "Tres"):
            register_song_request(guest_data=guest_data(), song_data=self.song(t), experience=STARS)
        with self.assertRaises(LimitReached):
            register_song_request(guest_data=guest_data(), song_data=self.song("Cuatro"))
        self.assertEqual(SongRequest.objects.count(), 3)

    def test_email_is_case_insensitive(self):
        for t in ("Uno", "Dos", "Tres"):
            register_song_request(guest_data=guest_data("ANA@Example.com"), song_data=self.song(t), experience=STARS)
        with self.assertRaises(LimitReached):
            register_song_request(guest_data=guest_data("ana@example.com"), song_data=self.song("Cuatro"))
        self.assertEqual(Guest.objects.count(), 1)

    def test_rejects_duplicate_song_ignoring_accents_and_case(self):
        register_song_request(guest_data=guest_data(), song_data=self.song("La Canción", "Héctor"))
        with self.assertRaises(DuplicateSong):
            register_song_request(guest_data=guest_data(), song_data=self.song("la cancion", "HECTOR"))

    @patch("apps.songs.thumbnails.spotify_thumbnail", return_value="https://i.scdn.co/image/abc")
    def test_platform_and_thumbnail_from_link(self, _mock):
        data = self.song("Uno")
        data["reference_url"] = "https://open.spotify.com/track/abc"
        song = register_song_request(guest_data=guest_data(), song_data=data)
        song.refresh_from_db()
        self.assertEqual(song.platform, SongRequest.Platform.SPOTIFY)
        self.assertEqual(song.thumbnail_url, "https://i.scdn.co/image/abc")

    @patch("apps.songs.thumbnails.spotify_thumbnail", side_effect=TimeoutError)
    def test_thumbnail_failure_does_not_block_request(self, _mock):
        data = self.song("Uno")
        data["reference_url"] = "https://open.spotify.com/track/abc"
        song = register_song_request(guest_data=guest_data(), song_data=data)
        self.assertEqual(song.thumbnail_url, "")


class ThumbnailTests(SimpleTestCase):
    def test_youtube_id_formats(self):
        for url in (
            "https://www.youtube.com/watch?v=sNPnbI1arSE&t=10",
            "https://youtu.be/sNPnbI1arSE?si=x",
            "https://music.youtube.com/watch?v=sNPnbI1arSE",
            "https://youtube.com/shorts/sNPnbI1arSE",
            "https://m.youtube.com/embed/sNPnbI1arSE",
        ):
            self.assertEqual(youtube_video_id(url), "sNPnbI1arSE", url)
        self.assertEqual(youtube_video_id("https://www.youtube.com/@canal"), "")

    def test_youtube_thumbnail_needs_no_network(self):
        self.assertEqual(
            fetch_thumbnail("https://youtu.be/sNPnbI1arSE"), "https://i.ytimg.com/vi/sNPnbI1arSE/hqdefault.jpg"
        )

    @patch("apps.songs.thumbnails.spotify_thumbnail", return_value="https://evil.example.com/x.jpg")
    def test_rejects_images_from_unknown_hosts(self, _mock):
        self.assertEqual(fetch_thumbnail("https://open.spotify.com/track/abc"), "")


@override_settings(SONG_MAX_PER_EMAIL=3)
class RequestViewTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club Prueba")
        self.url = reverse("songs:request_for_venue", args=[self.venue.slug])

    def post(self, title, email="ana@example.com", **extra):
        data = {**guest_data(email), "venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop", **STARS, **extra}
        return self.client.post(self.url, data)

    def test_success_flow_and_limit_message(self):
        for t in ("Uno", "Dos", "Tres"):
            self.assertEqual(self.post(t).status_code, 302)
        response = self.post("Cuatro")
        self.assertContains(response, "Gracias por tu buena energía")
        # Aunque llegó al límite, sigue viendo la cola de su discoteca para puntuar.
        self.assertContains(response, 'id="public-queue"')
        self.assertContains(response, f'data-venue="{self.venue.slug}"')
        self.assertContains(self.client.get(self.url), 'id="public-queue"')  # también al volver a entrar

    def test_success_page_shows_public_queue(self):
        response = self.client.get(self.post("Uno")["Location"])
        self.assertContains(response, 'id="public-queue"')

    def test_rejects_non_youtube_spotify_links(self):
        response = self.post("Uno", reference_url="https://example.com/song")
        self.assertContains(response, "Solo aceptamos enlaces de YouTube o Spotify")

    def test_my_requests_only_shows_own_songs(self):
        self.post("Mía")
        self.post("Ajena", email="otro@example.com")
        response = self.client.post(reverse("songs:my_requests"), {"email": "ana@example.com"}, follow=True)
        self.assertContains(response, "Mía")
        self.assertNotContains(response, "Ajena")

    def test_success_page_is_private_to_session(self):
        self.post("Uno")
        song = SongRequest.objects.get()
        other = self.client_class()
        self.assertEqual(other.get(reverse("songs:success", args=[song.pk])).status_code, 404)


@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=3, SONG_MAX_PER_IP=15, SONG_IP_ALLOWLIST=[],
                   TRUSTED_PROXY_COUNT=0)
class AbuseLimitTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club Prueba")
        self.url = reverse("songs:request_for_venue", args=[self.venue.slug])

    def post(self, client, title, email, ip="181.50.1.10"):
        data = {**guest_data(email), "venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop"}
        return client.post(self.url, data, REMOTE_ADDR=ip)

    def test_device_limit_applies_across_emails(self):
        phone = self.client  # misma cookie de dispositivo
        phone.get(self.url)
        for i in range(3):
            self.assertEqual(self.post(phone, f"Song {i}", f"p{i}@x.com").status_code, 302)
        response = self.post(phone, "Otra", "nuevo@x.com")
        self.assertContains(response, "Ya alcanzaste el máximo")
        self.assertNotContains(response, "Usar otro correo")
        self.assertEqual(SongRequest.objects.count(), 3)

    def test_device_limit_shown_on_get(self):
        self.client.get(self.url)
        for i in range(3):
            self.post(self.client, f"Song {i}", f"p{i}@x.com")
        self.client.post(reverse("songs:forget_me"))
        self.assertContains(self.client.get(self.url), "Ya alcanzaste el máximo")

    @override_settings(SONG_MAX_PER_IP=2)
    def test_ip_limit_is_generic_and_hides_ip(self):
        for i in range(2):
            self.assertEqual(self.post(self.client_class(), "Song", f"p{i}@x.com").status_code, 302)
        response = self.post(self.client_class(), "Song", "p9@x.com")
        self.assertContains(response, "Ya alcanzaste el máximo")
        self.assertNotContains(response, "181.50.1.10")
        # Otra IP sigue pudiendo pedir.
        self.assertEqual(self.post(self.client_class(), "Song", "p8@x.com", ip="190.0.0.1").status_code, 302)

    @override_settings(SONG_MAX_PER_IP=1, SONG_IP_ALLOWLIST=["181.50.1.0/24"])
    def test_allowlisted_network_is_exempt(self):
        for i in range(3):
            self.assertEqual(self.post(self.client_class(), "Song", f"p{i}@x.com").status_code, 302)

    def test_ip_and_device_are_stored_but_hidden_from_dj(self):
        self.post(self.client, "Uno", "ana@x.com")
        song = SongRequest.objects.get()
        self.assertEqual(song.client_ip, "181.50.1.10")
        self.assertEqual(len(song.device_id), 32)
        from apps.dj.serializers import serialize_request
        self.assertNotIn("181.50.1.10", str(serialize_request(song)))


class ClientIpTests(SimpleTestCase):
    def request(self, xff="", remote="10.0.0.5"):
        from django.test import RequestFactory
        return RequestFactory().get("/", HTTP_X_FORWARDED_FOR=xff, REMOTE_ADDR=remote)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_proxies_uses_remote_addr_and_ignores_spoofed_header(self):
        self.assertEqual(get_client_ip(self.request("1.2.3.4")), "10.0.0.5")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_cloudfront_plus_alb(self):
        # El cliente intenta falsificar "6.6.6.6"; CloudFront agrega la real y el ALB la del edge.
        self.assertEqual(get_client_ip(self.request("6.6.6.6, 181.50.1.10, 130.176.0.1")), "181.50.1.10")


class AnalysisTests(SimpleTestCase):
    def test_party_song_is_peak_with_highlight(self):
        comments = [
            ("Este temazo en la fiesta prende todo 🔥", 500),
            ("El drop en 2:10 es una locura", 300),
            ("2:10 brutal, a bailar", 120),
            ("Me encanta para el gym", 10),
        ] + [("buena", 0)] * 10
        result = analyze(comments, views=1_000_000, likes=50_000, duration=240)
        self.assertEqual(result["moment"], "peak")
        self.assertEqual(result["highlight"], "2:10")
        self.assertIn("🔥 Alta energía", result["tags"])
        self.assertIn("❤️ Muy querida por el público", result["tags"])
        self.assertTrue(result["low_confidence"])

    def test_nostalgic_song_goes_to_classics(self):
        comments = [("Un clásico de mi infancia, qué recuerdos", 900), ("Quién sigue escuchando esto", 400)] * 10
        result = analyze(comments, views=200_000_000, likes=1_000_000, duration=270)
        self.assertEqual(result["moment"], "classics")
        self.assertIn("🌎 Éxito masivo", result["tags"])
        self.assertFalse(result["low_confidence"])

    def test_ignores_timestamps_beyond_duration_and_no_comments(self):
        self.assertIsNone(analyze([("9:59 wow", 50)] * 5, duration=200)["highlight"])
        empty = analyze([])
        self.assertEqual(empty["moment"], "any")
        self.assertEqual(empty["tags"], [])

    def test_parse_duration(self):
        self.assertEqual(youtube.parse_duration("PT3M45S"), 225)
        self.assertEqual(youtube.parse_duration("PT1H2S"), 3602)


DETAILS = {
    "video_id": "sNPnbI1arSE", "title": "Video", "channel": "Canal", "published_at": "",
    "views": 900_000_000, "likes": 6_000_000, "comments": 300_000, "duration": 268,
}


@override_settings(YOUTUBE_API_KEY="test-key", ENRICH_ASYNC=False, YOUTUBE_SEARCH_FALLBACK=True)
class EnrichYouTubeTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club")

    def register(self, title="My Name Is", url="https://youtu.be/sNPnbI1arSE", email="ana@x.com"):
        song = {"venue": self.venue, "title": title, "artist": "Eminem", "genre": "hiphop", "reference_url": url}
        return register_song_request(guest_data=guest_data(email), song_data=song)

    @patch("apps.songs.youtube.top_comments", return_value=[("Un clásico, qué recuerdos", 100)] * 20)
    @patch("apps.songs.youtube.video_details", side_effect=lambda vid: dict(DETAILS))
    def test_stores_stats_and_recommendation(self, details, comments):
        song = self.register()
        song.refresh_from_db()
        self.assertEqual(song.youtube_data["views"], 900_000_000)
        self.assertEqual(song.youtube_data["analysis"]["moment"], "classics")
        # Segunda solicitud del mismo video usa la caché: no gasta cuota.
        self.register(title="Otra", email="b@x.com")
        self.assertEqual(details.call_count, 1)

    @patch("apps.songs.youtube.top_comments", return_value=[])
    @patch("apps.songs.youtube.video_details", side_effect=lambda vid: dict(DETAILS))
    @patch("apps.songs.youtube.search_video", return_value="sNPnbI1arSE")
    def test_searches_when_there_is_no_youtube_link(self, search, details, comments):
        song = self.register(url="")
        song.refresh_from_db()
        search.assert_called_once_with("Eminem My Name Is")
        self.assertEqual(song.youtube_data["source"], "search")
        self.assertTrue(song.thumbnail_url.startswith("https://i.ytimg.com/"))

    @patch("apps.songs.youtube.video_details", side_effect=youtube.YouTubeError("quotaExceeded"))
    def test_youtube_failure_never_blocks_request(self, details):
        song = self.register()
        song.refresh_from_db()
        self.assertEqual(song.youtube_data, {})

    @override_settings(YOUTUBE_API_KEY="")
    @patch("apps.songs.youtube.video_details")
    def test_without_api_key_nothing_is_called(self, details):
        self.register()
        details.assert_not_called()


class PublicQueueAndRatingTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club")
        guest = Guest.objects.create(email="ana@x.com", first_name="Ana María", last_name="Ruiz",
                                     phone="3001234567")
        mk = lambda title, **kw: SongRequest.objects.create(guest=guest, venue=self.venue, title=title,
                                                            artist="X", genre="pop", **kw)
        self.first, self.second = mk("Primera"), mk("Segunda")
        self.played = mk("Sonó", status=SongRequest.Status.PLAYED, status_changed_at=timezone.now())
        self.rejected = mk("Rechazada", status=SongRequest.Status.REJECTED)
        self.queue_url = reverse("songs:public_queue") + f"?venue={self.venue.slug}"

    def rate(self, song, stars, client=None):
        return (client or self.client).post(reverse("songs:rate_song", args=[song.pk]), {"stars": stars},
                                            content_type="application/json")

    def test_queue_is_ordered_and_hides_private_data(self):
        data = self.client.get(self.queue_url).json()
        self.assertEqual([s["title"] for s in data["pending"]], ["Primera", "Segunda"])
        self.assertEqual([s["title"] for s in data["played"]], ["Sonó"])
        raw = json.dumps(data)
        for private in ("ana@x.com", "3001234567", "Ruiz", "Rechazada"):
            self.assertNotIn(private, raw)
        self.assertEqual(data["pending"][0]["requester"], "Ana")

    def test_queue_accepts_venue_id_and_lists_all_without_venue(self):
        self.assertEqual(self.client.get(reverse("songs:public_queue") + f"?venue={self.venue.pk}").status_code, 200)
        Venue.objects.create(name="Otro")
        data = self.client.get(reverse("songs:public_queue")).json()
        self.assertEqual(len(data["pending"]), 2)
        self.assertEqual(data["pending"][0]["venue"], "Club")
        self.assertEqual(self.client.get(reverse("songs:public_queue") + "?venue=no-existe").status_code, 404)

    def test_public_link_uses_youtube_found_by_search(self):
        self.first.youtube_data = {"video_id": "sNPnbI1arSE"}
        self.first.save()
        item = self.client.get(self.queue_url).json()["pending"][0]
        self.assertEqual(item["link"], "https://www.youtube.com/watch?v=sNPnbI1arSE")
        self.assertEqual(item["platform"], "youtube")

    def test_one_vote_per_device_can_be_changed(self):
        self.assertEqual(self.rate(self.first, 5).status_code, 200)
        response = self.rate(self.first, 3)  # mismo dispositivo (misma cookie): cambia el voto
        self.assertEqual(response.json()["rating"], {"avg": 3.0, "count": 1, "mine": 3})
        other = self.client_class()
        self.assertEqual(self.rate(self.first, 5, other).json()["rating"]["count"], 2)
        self.assertEqual(SongRating.objects.filter(song=self.first).count(), 2)

    def test_my_vote_and_average_show_in_queue(self):
        self.rate(self.first, 4)
        self.client.get(self.queue_url)  # misma cookie
        item = self.client.get(self.queue_url).json()["pending"][0]
        self.assertEqual(item["rating"], {"avg": 4.0, "count": 1, "mine": 4})

    def test_invalid_votes_are_rejected(self):
        for value in (0, 6, "x", None):
            self.assertEqual(self.rate(self.first, value).status_code, 400, value)
        self.assertEqual(self.rate(self.rejected, 5).status_code, 404)
        self.assertEqual(self.client.get(reverse("songs:rate_song", args=[self.first.pk])).status_code, 405)

    def test_dj_sees_average_rating(self):
        from apps.dj.serializers import serialize_request
        from .api import with_ratings
        self.rate(self.first, 5)
        self.rate(self.first, 3, self.client_class())
        song = with_ratings(SongRequest.objects.filter(pk=self.first.pk)).get()
        self.assertEqual(serialize_request(song)["rating"]["avg"], 4.0)


@override_settings(SONG_MAX_PER_EMAIL=5, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class GuestIdentityTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(name="Club")
        self.url = reverse("songs:request_for_venue", args=[self.venue.slug])

    def post(self, title, client=None, **guest):
        data = {**guest_data(), "alias": "Anita", **guest, "venue": self.venue.pk, "title": title,
                "artist": "X", "genre": "pop"}
        return (client or self.client_class()).post(self.url, data)

    def test_same_email_must_keep_first_names_and_alias(self):
        self.assertEqual(self.post("Uno").status_code, 302)
        for changed in ({"first_name": "Carla"}, {"last_name": "Gómez"}, {"alias": "Otra"}):
            response = self.post("Dos", **changed)
            self.assertContains(response, "Este correo ya está registrado", msg_prefix=str(changed))
            self.assertContains(response, "No coincide con lo que registraste")
        self.assertEqual(SongRequest.objects.count(), 1)
        guest = Guest.objects.get()
        self.assertEqual((guest.first_name, guest.last_name, guest.alias), ("Ana", "Ruiz", "Anita"))

    def test_mismatch_message_does_not_reveal_registered_data(self):
        self.post("Uno")
        response = self.post("Dos", first_name="Intruso", last_name="Curioso", alias="Fisgon")
        self.assertNotContains(response, "Anita")
        self.assertNotContains(response, "Ruiz")

    def test_case_accents_and_spaces_do_not_matter(self):
        self.post("Uno", first_name="María José", alias="La Reina")
        self.assertEqual(self.post("Dos", first_name="  maria   jose ", alias="la reina").status_code, 302)

    def test_blank_alias_keeps_the_registered_one_and_phone_can_change(self):
        self.post("Uno")
        self.assertEqual(self.post("Dos", alias="", phone="3109998877").status_code, 302)
        guest = Guest.objects.get()
        self.assertEqual((guest.alias, guest.phone), ("Anita", "3109998877"))

    def test_alias_cannot_be_used_by_another_email(self):
        self.post("Uno")
        response = self.post("Dos", email="otra@x.com", first_name="Laura", alias="ANITA")
        self.assertContains(response, "Ese alias ya lo está usando otra persona")
        self.assertFalse(Guest.objects.filter(email="otra@x.com").exists())
        # Nombres repetidos entre personas distintas sí se permiten.
        self.assertEqual(self.post("Dos", email="otra@x.com", alias="").status_code, 302)

    def test_alias_can_be_added_later_if_free(self):
        self.post("Uno", alias="")
        self.assertEqual(self.post("Dos", alias="Nueva").status_code, 302)
        self.assertEqual(Guest.objects.get().alias, "Nueva")
        self.post("Tres", email="b@x.com", first_name="Beto", alias="")
        self.assertContains(self.post("Cuatro", email="b@x.com", first_name="Beto", alias="nueva"),
                            "Ese alias ya lo está usando otra persona")

    def test_known_guest_sees_locked_identity_fields(self):
        phone = self.client_class()
        self.post("Uno", client=phone)
        response = phone.get(self.url)
        self.assertContains(response, "¿No eres tú? Usar otro correo")
        self.assertContains(response, 'class="locked"', count=4)  # nombres, apellidos, correo, alias

    def test_alias_is_unique_in_database(self):
        from django.db import IntegrityError, transaction
        Guest.objects.create(email="a@x.com", first_name="A", last_name="B", phone="300", alias="Único")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Guest.objects.create(email="b@x.com", first_name="C", last_name="D", phone="300", alias="unico")



@override_settings(SONG_MAX_PER_EMAIL=3, SONG_MAX_PER_DEVICE=0, SONG_MAX_PER_IP=0, YOUTUBE_API_KEY="")
class ExperienceRatingTests(TestCase):
    """Calificación de la noche: obligatoria en la última canción del cupo, una vez por evento."""

    def setUp(self):
        from django.contrib.auth.models import Group, User
        from django.core.management import call_command

        from apps.dj.permissions import DJ_GROUP
        from apps.events.models import Event

        call_command("setup_roles", verbosity=0)
        self.dj = User.objects.create_user("djx", password="pass12345", first_name="DJ Cronso")
        self.dj.groups.add(Group.objects.get(name=DJ_GROUP))
        self.venue = Venue.objects.create(name="ClorofilaTaller")
        self.event = Event.objects.create(name="NaviRapas", venue=self.venue, max_per_person=3, dj=self.dj)
        self.phone = self.client_class()

    def post(self, title, url=None, **extra):
        data = {**guest_data(), "venue": self.venue.pk, "title": title, "artist": "X", "genre": "pop", **extra}
        return self.phone.post(url or self.event.get_absolute_url(), data)

    def test_only_the_last_song_asks_for_stars(self):
        self.assertEqual(self.post("Uno").status_code, 302)
        self.assertNotContains(self.phone.get(self.event.get_absolute_url()), "Califica tu noche")
        self.assertEqual(self.post("Dos").status_code, 302)
        page = self.phone.get(self.event.get_absolute_url())  # la próxima es la 3ra (última)
        self.assertContains(page, "Califica tu noche")
        self.assertContains(page, "ClorofilaTaller")
        self.assertContains(page, "NaviRapas")
        self.assertContains(page, "DJ Cronso")

    def test_third_song_is_blocked_without_stars(self):
        self.post("Uno")
        self.post("Dos")
        response = self.post("Tres")
        self.assertContains(response, "califica tu experiencia para enviarla")
        self.assertFalse(SongRequest.objects.filter(title="Tres").exists())
        # Faltando solo una de las tres también se bloquea
        self.assertContains(self.post("Tres", venue_stars=5, event_stars=4), "Elige de 1 a 5 estrellas")
        self.assertFalse(ExperienceRating.objects.exists())

    def test_third_song_with_stars_saves_rating_by_event_venue_and_dj(self):
        self.post("Uno")
        self.post("Dos")
        self.assertEqual(self.post("Tres", venue_stars=4, event_stars=5, dj_stars=3).status_code, 302)
        rating = ExperienceRating.objects.get()
        self.assertEqual((rating.venue, rating.event, rating.dj), (self.venue, self.event, self.dj))
        self.assertEqual((rating.venue_stars, rating.event_stars, rating.dj_stars), (4, 5, 3))
        self.assertEqual(rating.song.title, "Tres")
        self.assertEqual(rating.guest.email, "ana@example.com")

    def test_invalid_star_values_are_rejected(self):
        self.post("Uno")
        self.post("Dos")
        self.post("Tres", venue_stars=6, event_stars=0, dj_stars="x")
        self.assertFalse(SongRequest.objects.filter(title="Tres").exists())
        self.assertFalse(ExperienceRating.objects.exists())

    def test_event_cap_decides_which_song_is_last(self):
        from apps.events.models import Event
        short = Event.objects.create(name="Corto", venue=self.venue, max_per_person=1)
        self.assertContains(self.phone.post(short.get_absolute_url(), {**guest_data(), "venue": self.venue.pk,
                            "title": "Una", "artist": "X", "genre": "pop"}), "califica tu experiencia")
        # Evento sin DJ: solo local y evento
        ok = self.phone.post(short.get_absolute_url(), {**guest_data(), "venue": self.venue.pk, "title": "Una",
                             "artist": "X", "genre": "pop", "venue_stars": 5, "event_stars": 5})
        self.assertEqual(ok.status_code, 302)
        self.assertIsNone(ExperienceRating.objects.get().dj_stars)

    def test_without_event_only_the_venue_is_rated(self):
        url = reverse("songs:request_for_venue", args=[self.venue.slug])
        self.post("Uno", url=url)
        self.post("Dos", url=url)
        self.assertContains(self.post("Tres", url=url), "califica tu experiencia")
        self.assertEqual(self.post("Tres", url=url, venue_stars=2).status_code, 302)
        rating = ExperienceRating.objects.get()
        self.assertEqual((rating.event, rating.dj, rating.venue_stars, rating.event_stars), (None, None, 2, None))

    def test_asked_only_once_per_event_even_after_limit_reset(self):
        from django.contrib.auth.models import User
        from .services import reset_limit
        self.post("Uno")
        self.post("Dos")
        self.post("Tres", venue_stars=5, event_stars=5, dj_stars=5)
        reset_limit(Guest.objects.get(), User.objects.get(username="djx"), self.event)
        self.post("Cuatro")
        self.post("Cinco")
        self.assertEqual(self.post("Seis").status_code, 302)  # ya calificó este evento: no se vuelve a pedir
        self.assertEqual(ExperienceRating.objects.count(), 1)

    def test_admin_and_dj_see_averages(self):
        from django.contrib.auth.models import User
        self.post("Uno")
        self.post("Dos")
        self.post("Tres", venue_stars=4, event_stars=5, dj_stars=3)
        User.objects.create_superuser("admin", "a@x.com", "pass12345")
        admin = self.client_class()
        admin.login(username="admin", password="pass12345")
        dashboard = admin.get(reverse("control:dashboard"))
        self.assertContains(dashboard, "Calificaciones de la noche")
        self.assertEqual(dashboard.context["ratings"]["djs"][0].avg, 3)
        self.assertContains(admin.get(reverse("control:events")), "★ 5,0")
        dj = self.client_class()
        dj.login(username="djx", password="pass12345")
        self.assertContains(dj.get(reverse("events:dj_list")), "Tu calificación ★ 3,0")
