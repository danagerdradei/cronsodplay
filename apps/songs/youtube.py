"""
Cliente mínimo de la YouTube Data API v3 (gratis con API key, cuota diaria de 10.000 unidades).

Costos de cuota por canción: videos.list = 1, commentThreads.list = 1, search.list = 100
(la búsqueda solo se usa si la canción no trae link de YouTube).
"""
import json
import logging
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3/"
TIMEOUT_SECONDS = 6
MUSIC_CATEGORY_ID = "10"
DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


class YouTubeError(Exception):
    pass


def is_configured():
    return bool(settings.YOUTUBE_API_KEY)


def _get(endpoint, **params):
    params["key"] = settings.YOUTUBE_API_KEY
    request = Request(API_BASE + endpoint + "?" + urlencode(params), headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (URL fija https)
            return json.loads(response.read())
    except HTTPError as exc:
        reason = ""
        try:
            reason = json.loads(exc.read())["error"]["errors"][0]["reason"]
        except Exception:  # noqa: BLE001
            pass
        raise YouTubeError(reason or f"HTTP {exc.code}") from exc


def parse_duration(iso):
    """'PT3M45S' -> 225 segundos."""
    match = DURATION_RE.match(iso or "")
    if not match:
        return None
    h, m, s = (int(x or 0) for x in match.groups())
    return h * 3600 + m * 60 + s


def _int_or_none(value):
    return int(value) if value not in (None, "") else None


def video_details(video_id):
    """Vistas, likes, comentarios, duración, título y canal. None si el video no existe."""
    data = _get("videos", part="snippet,statistics,contentDetails", id=video_id)
    items = data.get("items") or []
    if not items:
        return None
    item = items[0]
    stats, snippet = item.get("statistics", {}), item.get("snippet", {})
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "views": _int_or_none(stats.get("viewCount")),
        "likes": _int_or_none(stats.get("likeCount")),  # None si el canal oculta los likes
        "comments": _int_or_none(stats.get("commentCount")),
        "duration": parse_duration(item.get("contentDetails", {}).get("duration")),
    }


def top_comments(video_id, limit=100):
    """Lista de (texto, likes) de los comentarios más relevantes. [] si están desactivados."""
    try:
        data = _get(
            "commentThreads",
            part="snippet",
            videoId=video_id,
            order="relevance",
            maxResults=min(limit, 100),
            textFormat="plainText",
        )
    except YouTubeError as exc:
        if str(exc) in ("commentsDisabled", "forbidden"):
            return []
        raise
    comments = []
    for item in data.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        comments.append((top.get("textDisplay", ""), int(top.get("likeCount", 0))))
    return comments


def search_video(query):
    """ID del primer video musical que coincide con la búsqueda (cuesta 100 unidades)."""
    data = _get(
        "search", part="id", type="video", maxResults=1, q=query, videoCategoryId=MUSIC_CATEGORY_ID
    )
    items = data.get("items") or []
    return items[0]["id"]["videoId"] if items else None
