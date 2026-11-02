/**
 * Cola pública en tabla + puntuación con estrellas (vanilla JS, sin dependencias).
 * Consume: GET  /cola/?venue=<slug o id>   (sin venue: todas las discotecas)
 *          POST /cola/<id>/calificar/      {"stars": 1-5}
 */
(() => {
  const root = document.getElementById("public-queue");
  if (!root) return;

  const API = root.dataset.url;
  const RATE_URL = root.dataset.rateUrl; // termina en /0/calificar/
  const POLL_MS = Number(root.dataset.poll || 15) * 1000;
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
  const venueSelect = document.getElementById("id_venue");
  const canHover = window.matchMedia("(hover: hover)").matches;

  const list = document.getElementById("pq-list");
  const played = document.getElementById("pq-played");
  const playedWrap = document.getElementById("pq-played-wrap");
  const empty = document.getElementById("pq-empty");
  const count = document.getElementById("pq-count");
  const venueLabel = document.getElementById("pq-venue-label");
  const tpl = document.getElementById("pq-tpl");

  const eventCode = root.dataset.event || "";
  let venue = root.dataset.venue || venueSelect?.value || "";

  function paintStars(row, value) {
    row.querySelectorAll("[data-stars]").forEach((b) => {
      b.classList.toggle("on", Number(b.dataset.stars) <= (value || 0));
    });
  }

  function avgText(rating) {
    if (!rating.count) return "Sin votos";
    return `${rating.avg.toFixed(1)} · ${rating.count} voto${rating.count === 1 ? "" : "s"}`;
  }

  function row(song, allVenues) {
    const tr = tpl.content.firstElementChild.cloneNode(true);
    tr.dataset.id = song.id;
    tr.querySelector(".pq-pos").textContent = song.position ?? "✓";
    tr.querySelector(".pq-title").textContent = song.title;
    tr.querySelector(".pq-artist").textContent = `${song.artist} · ${song.genre_label}`;
    tr.querySelector(".pq-by").textContent = song.requester;
    tr.querySelector(".pq-avg").textContent = avgText(song.rating);
    if (allVenues) {
      const v = tr.querySelector(".pq-venue");
      v.textContent = `📍 ${song.venue}`;
      v.hidden = false;
    }
    if (song.thumbnail_url) {
      const img = document.createElement("img");
      img.className = "song-thumb pq-thumb";
      img.src = song.thumbnail_url;
      img.alt = "";
      img.referrerPolicy = "no-referrer";
      tr.querySelector(".pq-thumb").replaceWith(img);
    }
    if (song.link) {
      const a = tr.querySelector(".pq-link");
      a.href = song.link;
      CronsoPlatform.decorate(a, song.platform);
      a.hidden = false;
      tr.querySelector(".pq-nolink").hidden = true;
    }
    paintStars(tr, song.rating.mine);
    if (song.rating.mine) tr.classList.add("rated");
    return tr;
  }

  function render(target, songs, allVenues) {
    const frag = document.createDocumentFragment();
    songs.forEach((s) => frag.appendChild(row(s, allVenues)));
    target.replaceChildren(frag);
  }

  async function load() {
    // No re-pintar mientras el mouse está sobre la tabla (en táctil :hover queda "pegado").
    if (canHover && root.matches(":hover") && list.children.length) return;
    try {
      const params = new URLSearchParams();
      if (eventCode) params.set("event", eventCode);
      else if (venue) params.set("venue", venue);
      const qs = params.toString();
      const url = qs ? `${API}?${qs}` : API;
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      const allVenues = !data.venue;
      venueLabel.textContent = data.event
        ? `${data.event.name} · ${data.venue.name}`
        : data.venue ? data.venue.name : "Todas las discotecas";
      render(list, data.pending, allVenues);
      render(played, data.played, allVenues);
      count.textContent = data.pending.length;
      empty.hidden = data.pending.length > 0;
      list.closest("table").hidden = data.pending.length === 0;
      playedWrap.hidden = data.played.length === 0;
    } catch (_) {
      /* reintenta en el siguiente ciclo */
    }
  }

  async function rate(tr, stars) {
    paintStars(tr, stars);
    tr.classList.add("rated");
    const avg = tr.querySelector(".pq-avg");
    try {
      const res = await fetch(RATE_URL.replace("/0/", `/${tr.dataset.id}/`), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ stars }),
      });
      if (res.status === 401) {
        paintStars(tr, 0);
        tr.classList.remove("rated");
        avg.innerHTML = "";
        const a = document.createElement("a");
        a.href = `/entrar/?next=${encodeURIComponent(location.pathname)}`;
        a.textContent = "Entra con Google para puntuar";
        avg.appendChild(a);
        return;
      }
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      avg.textContent = `${avgText(data.rating)} · ¡Gracias!`;
    } catch (_) {
      avg.textContent = "No se pudo guardar";
    }
  }

  root.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-stars]");
    if (btn) rate(btn.closest(".pq-row"), Number(btn.dataset.stars));
  });

  venueSelect?.addEventListener("change", () => {
    venue = venueSelect.value;
    list.replaceChildren();
    load();
  });

  document.addEventListener("visibilitychange", () => !document.hidden && load());
  load();
  setInterval(() => !document.hidden && load(), POLL_MS);
})();
