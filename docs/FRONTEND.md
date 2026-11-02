# Frontend — Cronso Dplay

## 1. Decisiones

| Decisión | Por qué |
|---|---|
| Plantillas Django (server-side rendering) | Primera carga rápida en celulares con mala señal dentro de la discoteca; sin build ni Node en producción |
| **Un** CSS propio (`static/css/app.css`, ~12 KB) | Sin Bootstrap/Tailwind: menos peso y diseño a medida |
| **Un** JS vanilla (`static/js/dj-panel.js`, ~5 KB) solo en el panel DJ | Las páginas del asistente funcionan sin JavaScript |
| Fuente *Outfit* (Google Fonts, `display=swap`) con *fallback* del sistema | Estética moderna sin bloquear el render |
| QR en SVG generado por el servidor (`segno`) | Nítido al imprimir, sin librerías JS |

Peso total de una página del asistente: **HTML ~6 KB + CSS ~13 KB + insignia 5 KB** (+ fuente). El inicio suma el logo grande (~50 KB).

## 2. Identidad visual

La paleta sale del logo **Cronso** (búho, [static/img/cronsologo.jpeg](../static/img/cronsologo.jpeg)), medida por píxel sobre la imagen original:

| Token | Valor | Origen en el logo | Uso |
|---|---|---|---|
| `--bg` | `#000000` | Fondo negro | Fondo de la página |
| `--primary` | `#c9a21c` | Contorno dorado | Botones, pasos, posición en la cola, bordes activos |
| `--primary-2` / `--primary-dark` | `#e6c34a` / `#9c8418` | Brillo y sombra del dorado | Gradiente dorado, enlaces |
| `--on-primary` | `#0a0a0a` | — | Texto sobre dorado (contraste AA) |
| `--text` | `#fcfcfc` | Letras "KONS" | Texto principal |
| `--muted` | `#a8a8a8` | Plateado del búho | Texto secundario |
| `--accent` | `#b4a890` | Beige/taupe de la cara | Etiquetas pequeñas |
| `--ok` / `--warn` / `--danger` | verde / dorado / rojo | — | Estados: sonó / en cola / no disponible |

El fondo tiene brillos dorados y plateados suaves (`.bg-glow`) que se apagan si el usuario prefiere menos movimiento (`prefers-reduced-motion`).

### Archivos del logo

| Archivo | Uso | Peso |
|---|---|---|
| `cronsologo.jpeg` | Original (fuente, no se usa en las páginas) | 100 KB |
| `logo-cronso.webp` | Logo completo con fondo transparente: inicio y QR imprimible | ~50 KB |
| `logo-owl.webp` | Cabeza del búho: insignia redonda de la barra superior | ~5 KB |
| `favicon.png` / `apple-touch-icon.png` | Ícono de la pestaña y del acceso directo en celular | 3 / 15 KB |

Si cambia el logo, se regeneran a partir del original: se recorta al contenido, se quita solo el negro exterior (el negro interno del búho se conserva) y se exporta en WebP.

## 3. Responsive (mobile-first)

- Diseño base para 360–430 px; a partir de **640 px** el formulario pasa a 2 columnas; a partir de **760 px** las filas del panel DJ se ponen en una línea.
- Inputs de **16 px** (evita el zoom automático de iOS), alto mínimo 46–48 px (área táctil).
- `inputmode` y `autocomplete` en celular/correo/nombres → teclado correcto y autocompletado.
- `viewport-fit=cover` + `env(safe-area-inset-*)` para iPhone con notch.
- Barra superior *sticky* con `backdrop-filter`.
- Estilos de impresión para la página del QR (oculta barra, fondo blanco).

## 4. Pantallas

| Ruta | Plantilla | Descripción |
|---|---|---|
| `/` | `core/home.html` | Hero + listado de discotecas activas |
| `/pedir/` y `/pedir/<slug>/` | `songs/request_form.html` | Formulario en 2 pasos (canción, datos). Indicador de cupo ●●● |
| (misma página `/pedir/…`) | `songs/request_form.html` + `static/js/public-queue.js` | **Cola en vivo en tabla** al lado del formulario (dos columnas desde 1140 px; debajo en celular, donde cada fila se vuelve tarjeta). Columnas: **#, Canción** (portada, título, artista, género), **Pedida por** (alias o primer nombre), **Link** (YouTube/Spotify) y **Puntuación** (estrellas 1–5 + promedio). Sin discoteca elegida muestra todas, con la discoteca de cada canción; si solo hay una activa, el formulario la preselecciona. Refresca cada 15 s y no repinta mientras el mouse está encima |
| `/pedido/<id>/` | `songs/success.html` | Confirmación, posición en la cola, cupo restante |
| (al exceder) | `songs/limit_reached.html` | Mensaje amable de límite + "Usar otro correo" |
| `/mis-canciones/` | `songs/my_requests.html` | Consulta por correo con estado de cada canción |
| `/dj/login/` | `dj/login.html` | Acceso DJ/Admin |
| `/dj/` | `dj/panel.html` | Cola en vivo con pestañas y filtro por discoteca |
| `/v/<slug>/qr/` | `venues/qr_print.html` | QR imprimible (solo staff) |

Componentes reutilizables: `templates/partials/star_input.html` (1–5 estrellas sin JavaScript: radios en orden 5→1 + `flex-direction: row-reverse`), `templates/partials/field.html` (label + input + errores + marca de obligatorio/opcional) y `templates/partials/song_thumb.html` (portada de YouTube/Spotify o un recuadro con ♪ si no hay).

## 5. Panel DJ (`dj-panel.js`)

- Consulta `GET /dj/api/requests/` cada `DJ_PANEL_POLL_SECONDS` (8 s) y al volver a la pestaña; **pausa** el sondeo si la pestaña está oculta.
- Renderiza con `<template>` + `textContent` (sin `innerHTML` → sin XSS con datos del público).
- Resalta en cian las canciones nuevas, muestra el número de pendientes en el título de la pestaña: `(4) Cronso Dplay`.
- Muestra los datos de YouTube cuando llegan: `▶ 500 M vistas · 👍 4 M · ⏱ 4:28` (formato compacto con `Intl.NumberFormat`) y chips de recomendación: el **momento sugerido** en dorado (*Pico de la noche*, *Bloque de clásicos*, *Warm-up o cierre*, *Cualquier momento*), el minuto destacado y etiquetas. Al pasar el mouse se ve cuántos comentarios se analizaron.
- **Módulos del DJ:** menú superior *🎵 Cola · 🎉 Eventos · ♻️ Límites* (`templates/dj/_tabs.html`). En la cola, filtros por **evento** y por discoteca (se recuerdan en `localStorage`).
- **Botones de plataforma** ([static/js/platform.js](../static/js/platform.js)): YouTube en rojo `#FF0000` y Spotify en verde `#1DB954`, cada uno con su ícono SVG (dibujado en el archivo, sin peticiones externas). Se usan en el panel del DJ y en la cola pública.
- Muestra el promedio de estrellas del público junto a la hora: `· ⭐ 4.3 (12)`.
- Botones **📋 Link** (copia la URL de la canción: la que pegó la persona o la de YouTube encontrada por búsqueda) y **📋 Búsqueda** (copia "Artista Canción" para pegar en el software de DJ). Usan `navigator.clipboard` y, por HTTP en la red local donde esa API no existe, el método clásico con `execCommand('copy')`.
- Botones ✓ (sonó), ✕ (no disponible), ↺ (devolver a la cola) → `POST /dj/api/requests/<id>/status/` con `X-CSRFToken`.
- Recuerda la discoteca elegida en `localStorage` (con `try/catch`).
- Indicador "en vivo" (punto verde) que se vuelve rojo si se pierde la conexión.

## 6. Accesibilidad

- Etiquetas `<label for>` en todos los campos, errores debajo del campo.
- `aria-live` en el contador de cupo y en la cola del DJ.
- Contraste de texto sobre fondo oscuro ≥ 4.5:1 en el texto principal.
- Prevención de doble envío del formulario (botón deshabilitado + "Enviando…").

## 7. Cómo extender

- Nuevos estilos: agregar a `app.css` reutilizando los tokens de `:root`; no añadir frameworks CSS.
- Nuevo JS: un archivo por pantalla en `static/js/`, cargado con `defer` solo en la plantilla que lo usa.
- Si algún día se necesita interactividad mayor sin SPA, la opción recomendada es **htmx** (~14 KB).
