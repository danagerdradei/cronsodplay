"""
Recomendación de uso para el DJ a partir de los comentarios de YouTube (reglas, sin IA).

Cada comentario pesa más cuantos más likes tiene: peso = 1 + ln(1 + likes).
Se mide qué parte del peso total menciona cada tema (energía, nostalgia, calma,
cantar en coro) y qué minuto del video se comenta más. Los textos de los
comentarios NO se guardan: solo el resultado.
"""
import math
import re
import unicodedata

ENERGY = (
    "🔥", "fuego", "temazo", "temon", "perreo", "banger", "hype", "drop", "fiesta", "party", "bailar",
    "baila", "dance", "prende", "rumba", "gym", "energia", "energy", "brutal", "insane", "fire", "slaps",
    "bop", "duro", "locura", "explot",
)
NOSTALGIA = (
    "clasico", "classic", "nostalgi", "infancia", "childhood", "old school", "throwback", "recuerdo",
    "memories", "epoca", "los 90", "los 2000", "90s", "2000s", "still listening", "quien sigue",
    "aun en 20", "todavia en 20", "who's here in 20", "escuchando en 20", "legend", "leyenda",
)
CHILL = (
    "relax", "chill", "tranquil", "calma", "lento", "dormir", "sleep", "triste", "sad", "llor", "cry",
    "romantic", "despecho", "melancol", "vibe suave",
)
SING = ("coro", "chorus", "cantar", "cantando", "sing", "letra", "lyrics", "himno", "anthem", "a todo pulmon")
POSITIVE = (
    "mejor", "best", "amo ", "love", "genial", "increible", "perfect", "obra maestra", "masterpiece",
    "goat", "top", "hermos", "beautiful", "❤", "😍",
)
NEGATIVE = ("malo", "horrible", "worst", "peor", "aburr", "boring", "cringe", "trash", "basura", "odio", "hate")

TIMESTAMP_RE = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d)(?![\d:])")

MOMENTS = {
    "peak": "Pico de la noche",
    "classics": "Bloque de clásicos",
    "chill": "Warm-up o cierre",
    "any": "Cualquier momento",
}


def _normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _share(weighted, keywords, total):
    hit = sum(w for text, w in weighted if any(k in text for k in keywords))
    return hit / total if total else 0.0


def _fmt_ts(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}"


def analyze(comments, views=None, likes=None, duration=None):
    """comments: lista de (texto, likes). Devuelve un dict serializable a JSON."""
    weighted = [(_normalize(text), 1 + math.log1p(max(n, 0))) for text, n in comments]
    total = sum(w for _, w in weighted)

    energy = _share(weighted, ENERGY, total)
    nostalgia = _share(weighted, NOSTALGIA, total)
    chill = _share(weighted, CHILL, total)
    sing = _share(weighted, SING, total)
    positive = _share(weighted, POSITIVE, total)
    negative = _share(weighted, NEGATIVE, total)

    # Minuto más comentado (ej. "2:10 el drop 🔥").
    stamps = {}
    for text, w in weighted:
        for mm, ss in {m for m in TIMESTAMP_RE.findall(text)}:
            sec = int(mm) * 60 + int(ss)
            if duration is None or sec <= duration:
                stamps[sec] = stamps.get(sec, 0) + w
    highlight = None
    if stamps:
        sec, score = max(stamps.items(), key=lambda kv: kv[1])
        if score >= 2:  # al menos ~2 comentarios lo mencionan
            highlight = _fmt_ts(sec)

    if energy >= 0.10 and energy >= chill:
        moment = "peak"
    elif nostalgia >= 0.10:
        moment = "classics"
    elif chill >= 0.08 and chill > energy:
        moment = "chill"
    else:
        moment = "any"

    tags = []
    if energy >= 0.10:
        tags.append("Alta energía")
    if nostalgia >= 0.10:
        tags.append("Clásico / nostalgia")
    if sing >= 0.05:
        tags.append("Para cantar en coro")
    if chill >= 0.08:
        tags.append("Ambiente tranquilo")
    if views and likes:
        ratio = likes / views
        if ratio >= 0.04:
            tags.append("Muy querida por el público")
        elif ratio >= 0.02:
            tags.append("Buena aceptación")
    if views and views >= 100_000_000:
        tags.append("Éxito masivo")
    if comments and negative > positive and negative >= 0.05:
        tags.append("Opiniones divididas")

    return {
        "moment": moment,
        "moment_label": MOMENTS[moment],
        "tags": tags,
        "highlight": highlight,
        "comments_analyzed": len(comments),
        "low_confidence": len(comments) < 15,
        "scores": {k: round(v, 3) for k, v in {
            "energy": energy, "nostalgia": nostalgia, "chill": chill, "sing": sing,
            "positive": positive, "negative": negative,
        }.items()},
    }
