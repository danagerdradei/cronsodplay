"""
Portadas de canciones a partir del link de referencia, sin API keys.

- YouTube: la miniatura se deriva del ID del video (i.ytimg.com), sin peticiones.
- Spotify: se consulta el oEmbed público (open.spotify.com/oembed).

Cualquier fallo devuelve "" para que el registro de la canción nunca se bloquee.
"""
import json
import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 4
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Solo se guardan imágenes servidas por los CDN oficiales.
ALLOWED_IMAGE_HOSTS = ("ytimg.com", "scdn.co", "spotifycdn.com")


def _host(url):
    return (urlparse(url).hostname or "").lower()


def _host_allowed(url, hosts):
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in hosts)


def youtube_video_id(url):
    """Extrae el ID de watch?v=, youtu.be/, /shorts/, /embed/, /live/ y music.youtube.com."""
    parsed = urlparse(url)
    host = _host(url)
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif _host_allowed(url, ("youtube.com",)):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                candidate = parts[1]
    return candidate if YOUTUBE_ID_RE.match(candidate) else ""


def youtube_thumbnail(url):
    video_id = youtube_video_id(url)
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""


def spotify_thumbnail(url):
    endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": url})
    request = Request(endpoint, headers={"User-Agent": "CronsoDplay/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (URL fija https)
        data = json.loads(response.read(64 * 1024))
    return data.get("thumbnail_url", "")


def fetch_thumbnail(url):
    """Devuelve la URL de la portada o "" si no se pudo obtener."""
    if not url:
        return ""
    try:
        if _host_allowed(url, ("youtube.com", "youtu.be")):
            thumb = youtube_thumbnail(url)
        elif _host_allowed(url, ("spotify.com",)):
            thumb = spotify_thumbnail(url)
        else:
            return ""
    except Exception as exc:  # noqa: BLE001 — red, JSON o timeout: nunca debe romper el pedido
        logger.warning("No se pudo obtener la portada de %s: %s", url, exc)
        return ""
    if thumb.startswith("https://") and _host_allowed(thumb, ALLOWED_IMAGE_HOSTS):
        return thumb
    return ""


# --- Vista previa del link y verificación contra la canción escrita ----------

STOPWORDS = {"the", "and", "feat", "ft", "official", "video", "audio", "lyric", "lyrics", "oficial", "remix",
             "letra", "con", "los", "las", "del", "que", "por", "una", "you", "for"}


def _oembed(url):
    """Título, autor y portada del link (oEmbed público de YouTube o Spotify, sin cuota ni API key)."""
    if _host_allowed(url, ("youtube.com", "youtu.be")):
        endpoint = "https://www.youtube.com/oembed?" + urlencode({"url": url, "format": "json"})
    elif _host_allowed(url, ("spotify.com",)):
        endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": url})
    else:
        return None
    request = Request(endpoint, headers={"User-Agent": "CronsoDplay/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (URL fija https)
        return json.loads(response.read(64 * 1024))


def _tokens(text):
    from .models import normalize_key

    return {t for t in normalize_key(text).split() if len(t) >= 3 and t not in STOPWORDS}


def link_matches_song(link_title, title, artist):
    """
    ¿El título del video/track se parece a la canción o al artista escritos?
    True si comparte alguna palabra significativa. Si no hay con qué comparar, True (no alarmar).
    """
    found = _tokens(link_title)
    wanted = _tokens(title) | _tokens(artist)
    if not found or not wanted:
        return True
    return bool(found & wanted)


def link_preview(url, title="", artist=""):
    """Datos para mostrar debajo del campo del link. None si el link no es válido o no responde."""
    try:
        data = _oembed(url)
    except Exception as exc:  # noqa: BLE001 — red, 404 (video privado/borrado), JSON…
        logger.info("Sin vista previa para %s: %s", url, exc)
        return None
    if not data:
        return None
    link_title = data.get("title", "")
    author = data.get("author_name", "")
    thumb = data.get("thumbnail_url", "")
    if not (thumb.startswith("https://") and _host_allowed(thumb, ALLOWED_IMAGE_HOSTS)):
        thumb = fetch_thumbnail(url)
    return {
        "title": link_title,
        "author": author,
        "thumbnail": thumb,
        "platform": "spotify" if _host_allowed(url, ("spotify.com",)) else "youtube",
        "matches": link_matches_song(f"{link_title} {author}", title, artist),
    }


def link_identity(url):
    """Identificador estable del contenido del link (ID de video de YouTube o ruta de Spotify)."""
    video_id = youtube_video_id(url)
    if video_id:
        return f"yt:{video_id}"
    if _host_allowed(url or "", ("spotify.com",)):
        path = urlparse(url).path.rstrip("/")
        return f"sp:{path.split('/')[-1]}" if path else ""
    return ""
