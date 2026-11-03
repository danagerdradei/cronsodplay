/**
 * Vista previa del link de YouTube/Spotify en el formulario de pedido.
 * Muestra qué video/track es realmente el link pegado y avisa si no parece
 * ser la canción escrita (no bloquea el envío). Consume GET /link-preview/.
 */
(() => {
  const box = document.getElementById("link-preview");
  const input = document.getElementById("id_reference_url");
  if (!box || !input) return;

  const title = document.getElementById("id_title");
  const artist = document.getElementById("id_artist");
  const img = box.querySelector("img");
  const name = box.querySelector("strong");
  const author = box.querySelector("small");
  const note = box.querySelector(".lp-note");
  let timer = null;
  let lastQuery = "";

  const looksLikeLink = (v) => /^https:\/\/([\w-]+\.)*(youtube\.com|youtu\.be|spotify\.com)\//i.test(v);

  async function check() {
    const url = input.value.trim();
    if (!looksLikeLink(url)) { box.hidden = true; lastQuery = ""; return; }
    const params = new URLSearchParams({ url, title: title?.value || "", artist: artist?.value || "" });
    const query = params.toString();
    if (query === lastQuery) return;
    lastQuery = query;
    try {
      const res = await fetch(`${box.dataset.url}?${query}`, { headers: { Accept: "application/json" } });
      if (!res.ok) {
        box.hidden = false;
        box.className = "link-preview warn";
        img.hidden = true;
        name.textContent = "No pudimos abrir este link";
        author.textContent = "";
        note.textContent = "⚠️ Revisa que sea un video o canción pública de YouTube o Spotify.";
        return;
      }
      const data = await res.json();
      box.hidden = false;
      img.hidden = !data.thumbnail;
      if (data.thumbnail) img.src = data.thumbnail;
      name.textContent = data.title || "Video sin título";
      author.textContent = data.author ? `${data.platform === "spotify" ? "Spotify" : "YouTube"} · ${data.author}` : "";
      const hasSong = (title?.value || "").trim() || (artist?.value || "").trim();
      if (!hasSong) {
        box.className = "link-preview";
        note.textContent = "Este es el video que verá el DJ.";
      } else if (data.matches) {
        box.className = "link-preview ok";
        note.textContent = "✓ Coincide con tu canción";
      } else {
        box.className = "link-preview warn";
        note.textContent = "⚠️ Este link parece ser de otra canción. Revisa que sea la que estás pidiendo.";
      }
    } catch (_) {
      box.hidden = true;  // sin conexión: no molestar
    }
  }

  const schedule = () => { clearTimeout(timer); timer = setTimeout(check, 450); };
  input.addEventListener("input", schedule);
  input.addEventListener("paste", () => setTimeout(check, 50));
  title?.addEventListener("change", check);
  artist?.addEventListener("change", check);
  if (input.value) check();  // al volver con errores del formulario
})();
