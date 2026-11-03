/**
 * Panel DJ — cola de canciones en vivo (vanilla JS, sin dependencias).
 * Consume: GET  /dj/api/requests/?venue=&status=
 *          POST /dj/api/requests/<id>/status/   {"status": "..."}
 */
(() => {
  const root = document.getElementById("dj-panel");
  if (!root) return;

  const API = root.dataset.api;
  const STATUS_URL = root.dataset.statusUrl; // termina en /0/status/
  const DELETE_URL = root.dataset.deleteUrl; // termina en /0/delete/
  const POLL_MS = Number(root.dataset.poll || 8) * 1000;
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;

  const queue = document.getElementById("queue");
  const empty = document.getElementById("empty");
  const error = document.getElementById("error");
  const liveDot = document.querySelector(".live-dot");
  const tpl = document.getElementById("row-tpl");
  const venueSelect = document.getElementById("venue-filter");
  const eventSelect = document.getElementById("event-filter");
  const baseTitle = document.title;

  let savedVenue = "";
  let savedEvent = "";
  try {
    savedVenue = localStorage.getItem("dj.venue") || "";
    savedEvent = localStorage.getItem("dj.event") || "";
  } catch (_) {}

  const state = {
    status: "pending",
    venue: "",
    event: "",
    seen: new Set(),
    firstLoad: true,
    timer: null,
  };
  // Página de playlist de un evento: el evento es fijo y no hay selectores.
  const fixedEvent = root.dataset.fixedEvent || "";
  if (fixedEvent) {
    state.event = fixedEvent;
  } else {
    venueSelect.value = savedVenue;
    state.venue = venueSelect.value; // vacío si la discoteca guardada ya no existe
    eventSelect.value = savedEvent;
    state.event = eventSelect.value; // vacío si el evento ya se cerró
  }


  function render(items) {
    const frag = document.createDocumentFragment();
    for (const it of items) {
      const li = tpl.content.firstElementChild.cloneNode(true);
      li.dataset.id = it.id;
      li.querySelector(".pos").textContent = state.status === "pending" ? it.position : "";
      li.querySelector(".q-title").textContent = it.title;
      li.querySelector(".q-artist").textContent = it.artist;
      if (it.requester_email) {
        const mail = li.querySelector(".q-email");
        mail.href = `mailto:${it.requester_email}`;
        CronsoPlatform.withIcon(mail, "mail", it.requester_email);
        mail.title = `Escribir a ${it.requester}`;
        mail.hidden = false;
      }
      li.querySelector(".q-meta").textContent =
        `${it.genre_label} · pedida por ${it.requester} · ${it.created_at_display}` +
        (state.venue ? "" : ` · ${it.venue.name}`) +
        (it.event && !state.event ? ` · ${it.event}` : "") +
        (it.rating?.count ? ` · ★ ${it.rating.avg.toFixed(1)} (${it.rating.count})` : "");
      if (it.thumbnail_url) {
        const img = document.createElement("img");
        img.className = "q-thumb song-thumb";
        img.src = it.thumbnail_url;
        img.alt = "";
        img.loading = "lazy";
        img.referrerPolicy = "no-referrer";
        li.querySelector(".q-thumb").replaceWith(img);
      }
      const link = it.reference_url || it.youtube?.url;
      li.dataset.search = `${it.artist} ${it.title}`;
      if (link) {
        const a = li.querySelector(".q-link");
        a.href = link;
        if (it.reference_url) CronsoPlatform.decorate(a, it.platform);
        else CronsoPlatform.decorate(a, "youtube", "búsqueda");
        a.hidden = false;
        li.dataset.link = link;
        li.querySelector('[data-copy="link"]').hidden = false;
      }
      if (it.youtube) renderYouTube(li, it.youtube);
      // Mostrar solo las acciones que tienen sentido en la pestaña actual.
      li.querySelectorAll("[data-action]").forEach((b) => {
        b.hidden = b.dataset.action === state.status;
      });
      if (!state.firstLoad && !state.seen.has(it.id)) li.classList.add("is-new");
      state.seen.add(it.id);
      frag.appendChild(li);
    }
    queue.replaceChildren(frag);
    empty.hidden = items.length > 0;
  }

  const compact = new Intl.NumberFormat("es-CO", { notation: "compact", maximumFractionDigits: 1 });
  const duration = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  // Ícono de cada etiqueta de la recomendación (las guardadas antes traían un emoji delante: se quita).
  const TAG_ICONS = {
    "Alta energía": "flame", "Clásico / nostalgia": "history", "Para cantar en coro": "mic",
    "Ambiente tranquilo": "moon", "Muy querida por el público": "heart", "Buena aceptación": "thumbs-up",
    "Éxito masivo": "globe", "Opiniones divididas": "scale",
  };

  function chip(text, cls = "", iconName = "") {
    const span = document.createElement("span");
    span.className = `chip ${cls}`.trim();
    if (iconName) CronsoPlatform.withIcon(span, iconName, text);
    else span.textContent = text;
    return span;
  }

  // Vistas, likes, duración y recomendación calculada de los comentarios de YouTube.
  function renderYouTube(li, yt) {
    const stats = [];
    if (yt.views != null) stats.push(`${compact.format(yt.views)} vistas`);
    if (yt.likes != null) stats.push(`${compact.format(yt.likes)} likes`);
    if (yt.duration) stats.push(duration(yt.duration));
    li.querySelector(".q-stats").textContent = stats.join("  ·  ");

    if (yt.title) {
      const vt = document.createElement("small");
      vt.className = "q-video-title";
      CronsoPlatform.withIcon(vt, "video", yt.title);
      li.querySelector(".q-stats").after(vt);
    }

    const reco = li.querySelector(".q-reco");
    if (yt.link_mismatch) reco.appendChild(chip("El link no coincide con la canción", "chip-warn", "alert"));
    if (yt.moment_label) reco.appendChild(chip(yt.moment_label, `chip-moment chip-${yt.moment}`));
    if (yt.highlight) reco.appendChild(chip(`Destacado ${yt.highlight}`, "", "target"));
    for (const raw of yt.tags || []) {
      const tag = raw.replace(/^[^\p{L}\p{N}]+/u, "");
      reco.appendChild(chip(tag, "", TAG_ICONS[tag] || ""));
    }
    if (yt.low_confidence) reco.appendChild(chip("pocos comentarios", "chip-muted"));
    reco.title = `Basado en ${yt.comments_analyzed} comentarios de YouTube` +
      (yt.found_by_search ? ` · video encontrado por búsqueda: ${yt.title}` : "");
    li.querySelector(".q-yt").hidden = false;
  }

  function renderCounts(counts) {
    for (const [k, v] of Object.entries(counts)) {
      const el = document.querySelector(`[data-count="${k}"]`);
      if (el) el.textContent = v;
    }
    document.title = counts.pending ? `(${counts.pending}) ${baseTitle}` : baseTitle;
  }

  async function load() {
    const params = new URLSearchParams({ status: state.status });
    if (state.venue) params.set("venue", state.venue);
    if (state.event) params.set("event", state.event);
    try {
      const res = await fetch(`${API}?${params}`, { headers: { Accept: "application/json" } });
      if (res.status === 401 || res.status === 403) return location.reload();
      if (!res.ok) throw new Error(res.status);
      const data = await res.json();
      renderCounts(data.counts);
      render(data.results);
      state.firstLoad = false;
      error.hidden = true;
      liveDot.classList.remove("off");
    } catch (e) {
      error.hidden = false;
      liveDot.classList.add("off");
    }
  }

  function schedule() {
    clearInterval(state.timer);
    state.timer = setInterval(() => !document.hidden && load(), POLL_MS);
  }

  async function changeStatus(id, status, li) {
    li.style.opacity = ".4";
    const res = await fetch(STATUS_URL.replace("/0/", `/${id}/`), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) li.style.opacity = "";
    load();
  }

  // --- Eventos ---
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      state.status = tab.dataset.status;
      state.firstLoad = true;
      load();
    })
  );

  eventSelect?.addEventListener("change", () => {
    state.event = eventSelect.value;
    try { localStorage.setItem("dj.event", state.event); } catch (_) {}
    state.firstLoad = true;
    load();
  });

  venueSelect?.addEventListener("change", () => {
    state.venue = venueSelect.value;
    try { localStorage.setItem("dj.venue", state.venue); } catch (_) {}
    state.firstLoad = true;
    load();
  });

  // Copiar al portapapeles. navigator.clipboard solo existe en HTTPS o localhost;
  // por la IP de la red local (http://192.168…) se usa el método clásico.
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    }
  }

  queue.addEventListener("click", async (e) => {
    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) {
      const li = copyBtn.closest(".queue-item");
      const ok = await copyText(li.dataset[copyBtn.dataset.copy] || "");
      copyBtn.dataset.label ??= copyBtn.innerHTML; // contenido fijo de la plantilla (ícono + texto)
      if (ok) CronsoPlatform.withIcon(copyBtn, "check", "Copiado");
      else copyBtn.textContent = "No se pudo copiar";
      copyBtn.classList.toggle("copied", ok);
      setTimeout(() => { copyBtn.innerHTML = copyBtn.dataset.label; copyBtn.classList.remove("copied"); }, 1500);
      return;
    }
    const delBtn = e.target.closest("[data-delete]");
    if (delBtn) {
      const li = delBtn.closest(".queue-item");
      const title = li.querySelector(".q-title").textContent;
      if (!confirm(`¿Eliminar "${title}" de la playlist? La persona recupera ese cupo. No se puede deshacer.`)) return;
      li.style.opacity = ".4";
      const res = await fetch(DELETE_URL.replace("/0/", `/${li.dataset.id}/`), {
        method: "POST", headers: { "X-CSRFToken": csrf },
      });
      if (res.ok) li.remove(); else { li.style.opacity = ""; alert("No se pudo eliminar (¿es de otro DJ?)."); }
      load();
      return;
    }
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const li = btn.closest(".queue-item");
    changeStatus(li.dataset.id, btn.dataset.action, li);
  });

  document.addEventListener("visibilitychange", () => !document.hidden && load());

  load();
  schedule();
})();
