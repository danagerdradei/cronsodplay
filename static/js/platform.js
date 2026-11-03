/**
 * Botones de plataforma (YouTube / Spotify) con su color e ícono.
 * Íconos SVG simples dibujados aquí: sin peticiones externas.
 * Uso: CronsoPlatform.decorate(<a>, "youtube" | "spotify" | "", "texto opcional")
 */
window.CronsoPlatform = (() => {
  const ICONS = {
    youtube:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="5" width="21" height="14" rx="4.2" fill="#fff"/>' +
      '<path d="M10 9v6l5.2-3z" fill="#FF0000"/></svg>',
    spotify:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5" fill="#000"/>' +
      '<path d="M6.6 9.4c3.7-1.1 7.8-.8 11 1.1M7.3 12.5c3-.8 6.2-.5 8.9 1M8 15.4c2.3-.6 4.6-.4 6.6.7" ' +
      'stroke="#1DB954" stroke-width="1.7" fill="none" stroke-linecap="round"/></svg>',
  };
  const NAMES = { youtube: "YouTube", spotify: "Spotify" };
  const SVG_NS = "http://www.w3.org/2000/svg";

  // Ícono de línea del sprite (static/img/icons.svg); la URL la pone base.html en <body data-icons>.
  function icon(name, cls = "") {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", `icon ${cls}`.trim());
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `${document.body.dataset.icons}#i-${name}`);
    svg.appendChild(use);
    return svg;
  }

  // Reemplaza el contenido de `el` por ícono + texto (el texto va como textContent, seguro).
  function withIcon(el, name, text) {
    el.replaceChildren(icon(name), document.createTextNode(` ${text}`));
    return el;
  }

  function decorate(a, platform, note = "") {
    a.classList.add("platform-btn");
    if (ICONS[platform]) a.classList.add(`platform-${platform}`);
    if (ICONS[platform]) a.innerHTML = ICONS[platform]; // íconos fijos de este archivo, no datos del usuario
    else a.replaceChildren(icon("link"));
    const label = document.createElement("span");
    label.textContent = NAMES[platform] || "Abrir link";
    a.appendChild(label);
    if (note) {
      const small = document.createElement("small");
      small.textContent = note;
      a.appendChild(small);
    }
    a.title = `Abrir en ${NAMES[platform] || "el navegador"}`;
    return a;
  }

  return { decorate, icon, withIcon };
})();
