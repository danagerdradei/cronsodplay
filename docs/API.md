# API y rutas — Cronso Dplay

Base local: `http://localhost:8000` · Producción: `https://dplay.cronso.com` (ejemplo).

## 1. Resumen

| Método | Ruta | Acceso | Formato | Descripción |
|---|---|---|---|---|
| GET | `/health/` | Público | JSON | Estado del servicio y la BD |
| GET | `/cola/?venue=<slug o id>` | Público | JSON | Cola en vivo para el público + últimas que sonaron |
| POST | `/cola/<id>/calificar/` | Público (cookie de dispositivo) | JSON | Puntuar de 1 a 5 estrellas |
| GET | `/` | Público | HTML | Inicio |
| GET/POST | `/pedir/` | Público | HTML | Formulario (eligiendo discoteca) |
| GET/POST | `/pedir/<venue_slug>/` | Público | HTML | Formulario con discoteca preseleccionada |
| GET | `/pedido/<id>/` | Sesión que creó el pedido | HTML | Confirmación |
| GET/POST | `/mis-canciones/` | Público (filtra por correo) | HTML | Canciones del correo |
| POST | `/mis-canciones/salir/` | Público | HTML | Olvida el correo de la sesión |
| GET | `/v/<slug>/` | Público | Redirect | **Destino del QR** → `/pedir/<slug>/` |
| GET/POST | `/e/<código>/` | Público | HTML | **Link/QR de un evento**: formulario con discoteca y cupo del evento (410 si el evento está cerrado) |
| GET | `/e/<código>/qr/` | Público | SVG/PNG | QR del evento. `?formato=png` para PNG, `&descargar=1` para descargar |
| GET/POST | `/dj/eventos/` | DJ | HTML | **Mis eventos**: solo los que creó ese DJ + crear. El Admin es redirigido a `/control/eventos/` |
| GET | `/dj/eventos/<código>/` | DJ (dueño) / Admin | HTML | Link, QR, compartir (WhatsApp / copiar / compartir nativo), resumen. Evento de otro DJ → 404 |
| GET | `/dj/eventos/<código>/playlist/` | DJ (dueño) / Admin | HTML | **Playlist del evento**: cola en vivo solo de ese evento (pestañas, YouTube, estrellas, ✓ ✕). El Admin ve además Editar y Reiniciar |
| POST | `/dj/eventos/<código>/estado/` | DJ / Admin | Redirect | Cerrar o reabrir el evento |
| GET | `/dj/eventos/<código>/imprimir/` | DJ / Admin | HTML | QR imprimible del evento |
| GET | `/dj/limites/?evento=<código>&q=<texto>` | DJ / Admin | HTML | Buscar personas (correo, nombre, alias); sin `q` lista a quienes llegaron al límite |
| POST | `/dj/limites/<guest_id>/restablecer/` | DJ / Admin | Redirect | Restablecer el cupo (campo `evento`; vacío = pedidos sin evento) |
| GET | `/v/<slug>/qr.svg` | Público | SVG | Imagen del QR (cache 24 h) |
| GET | `/v/<slug>/qr/` | Staff | HTML | QR imprimible |
| GET | `/entrar/?next=<ruta>` | Público | HTML | Botón "Continuar con Google" |
| POST | `/auth/google/` | Público (CSRF) | JSON | Body `{credential, next}` → `{redirect}` o `400 {error}` |
| POST | `/salir/` | Asistente | Redirect | Cerrar sesión de Google en la app |
| GET/POST | `/perfil/` | Asistente | HTML | Perfil, celular/alias, cupos por evento, historial |
| GET | `/control/` | Admin | HTML | Resumen de la plataforma |
| GET/POST | `/control/usuarios/` · `/control/usuarios/<id>/` · POST `/control/usuarios/<id>/contrasena/` | Admin | HTML | Crear y editar usuarios DJ/Admin, cambiar contraseña |
| GET | `/control/personas/?q=&orden=` · `/control/personas/exportar/` | Admin | HTML / CSV | Personas con contacto completo, búsqueda, exportación |
| GET · POST | `/control/personas/<id>/` · `/restablecer/` · `/eliminar/` | Admin | HTML | Detalle, restablecer cupo, eliminar (exige escribir el correo) |
| GET/POST | `/control/eventos/` | Admin | HTML | Administrar eventos: crear, lista con acciones |
| GET/POST | `/control/eventos/<código>/` | Admin | HTML | Editar evento (nombre, discoteca, cupo, géneros) |
| POST | `/control/eventos/<código>/estado/` · `/control/eventos/<código>/eliminar/` | Admin | Redirect | Abrir/cerrar · eliminar con sus canciones (exige escribir el código) |
| POST | `/control/eventos/reiniciar/` | Admin | Redirect | **Reiniciar playlist**: campos `evento` y `confirmar` (= código). Borra las canciones y votos del evento; el evento, link y QR se conservan y todos recuperan su cupo |
| GET/POST · POST | `/control/discotecas/` · `/control/discotecas/<id>/estado/` | Admin | HTML | Crear y activar/desactivar discotecas |
| GET/POST | `/acceso/` · POST `/dj/logout/` | Público | HTML | **Acceso único DJ + Admin**. Sin `?next=`: Admin → `/control/`, DJ → `/dj/`. Usuarios sin rol no pueden entrar. `/dj/login/` y `/admin/login/` redirigen aquí |
| GET | `/dj/` | DJ / Admin | HTML | Panel DJ |
| GET | `/dj/api/requests/` | DJ / Admin | JSON | Cola de solicitudes |
| POST | `/dj/api/requests/<id>/status/` | DJ / Admin | JSON | Cambiar estado |
| — | `/admin/` | Admin | HTML | Django admin |

## 2. Autenticación de la API

- Sesión de Django (cookie `sessionid`) obtenida en `/dj/login/`.
- Las peticiones `POST` requieren el header **`X-CSRFToken`** con el valor de la cookie `csrftoken`.
- Errores:

| HTTP | Cuerpo | Causa |
|---|---|---|
| 401 | `{"error": "no_autenticado"}` | Sin sesión |
| 403 | `{"error": "sin_permiso"}` | Usuario sin grupo DJ/Administrador |
| 400 | `{"error": "estado_invalido"}` / `{"error": "json_invalido"}` | Parámetros incorrectos |
| 404 | HTML | Solicitud inexistente |

## 3. `GET /health/`

```json
200 {"status": "ok"}
503 {"status": "db_error"}
```
Usado por el health check del ALB y del `HEALTHCHECK` de Docker.

## 4. `GET /dj/api/requests/`

| Parámetro | Valores | Por defecto |
|---|---|---|
| `status` | `pending`, `played`, `rejected`, `all` | `pending` |
| `event` | código del evento | todos |
| `venue` | slug de la discoteca | todas |

Orden: `pending` → más antigua primero (**prioridad de llegada**); otros → más reciente primero. Máximo 300 resultados.

```bash
curl -b cookies.txt "http://localhost:8000/dj/api/requests/?status=pending&venue=cronso-club"
```

```json
{
  "server_time": "2026-11-02T23:41:10.120Z",
  "counts": {"pending": 4, "played": 12, "rejected": 1},
  "results": [
    {
      "id": 31,
      "position": 1,
      "title": "My Name Is",
      "artist": "Eminem",
      "genre": "hiphop",
      "genre_label": "Hip-Hop / Rap",
      "reference_url": "https://youtu.be/abc",
      "platform": "youtube",
      "thumbnail_url": "https://i.ytimg.com/vi/sNPnbI1arSE/hqdefault.jpg",
      "youtube": {
        "url": "https://www.youtube.com/watch?v=sNPnbI1arSE",
        "title": "…",
        "views": 500000000,
        "likes": 4000000,
        "duration": 268,
        "found_by_search": false,
        "moment": "classics",
        "moment_label": "Bloque de clásicos",
        "tags": ["📼 Clásico / nostalgia", "🎤 Para cantar en coro", "🌎 Éxito masivo"],
        "highlight": null,
        "comments_analyzed": 100,
        "low_confidence": false
      },
      "requester": "Anita",
      "venue": {"slug": "cronso-club", "name": "Cronso Club"},
      "status": "pending",
      "status_label": "En cola",
      "created_at": "2026-11-02T18:41:02-05:00",
      "created_at_display": "6:41 PM"
    }
  ]
}
```

> `youtube` es `null` si no hay API key, si YouTube aún no respondió (se consulta en segundo plano, aparece en el siguiente refresco del panel) o si no se encontró el video. `likes` es `null` si el canal los oculta.

> `counts` respeta el filtro `venue` pero no el de `status`. `requester` es el alias o, si no hay, "Nombres Apellidos". El correo y el celular **no** se exponen.

## 5. `POST /dj/api/requests/<id>/status/`

```bash
curl -b cookies.txt -X POST \
  -H "Content-Type: application/json" -H "X-CSRFToken: <token>" \
  -d '{"status": "played"}' \
  http://localhost:8000/dj/api/requests/31/status/
```

Respuesta `200`: el objeto de la solicitud con el mismo formato de §4 (`position` = `null`). Registra `status_changed_at` y `handled_by`.

## 6. Cola pública y estrellas ([apps/songs/api.py](../apps/songs/api.py))

### `GET /cola/?venue=cronso-club` o `GET /cola/?event=<código>`
Hasta 50 canciones en cola (en orden de llegada) y las 5 últimas que sonaron. **No incluye** correo, celular, apellidos, IP ni dispositivo; `requester` es el alias o solo el primer nombre.

```json
{
  "venue": {"slug": "cronso-club", "name": "Cronso Club"},
  "pending": [
    {"id": 1, "position": 1, "title": "My Name Is", "artist": "Eminem", "genre_label": "Hip-Hop / Rap",
     "thumbnail_url": "https://i.ytimg.com/vi/…/hqdefault.jpg", "requester": "Anita", "status": "pending",
     "rating": {"avg": 4.0, "count": 1, "mine": 4}}
  ],
  "played": []
}
```
`rating.mine` es el voto de este dispositivo (o `null`). Sin `venue` devuelve la cola de **todas** las discotecas activas (`venue: null` y cada canción trae su `venue`). Cada canción incluye `link` y `platform` (el link que pegó la persona o el video de YouTube encontrado por búsqueda). Error `404 {"error": "discoteca_no_encontrada"}` si el `venue` no existe.

### `POST /cola/<id>/calificar/`
Body `{"stars": 1-5}` + header `X-CSRFToken`. Un voto por dispositivo (cookie `dplay_device`); votar de nuevo **cambia** el voto. Solo canciones en cola o que ya sonaron (las "no disponibles" → 404). Respuesta: `{"id": 1, "rating": {"avg": 4.0, "count": 1, "mine": 4}}`. Error `400 {"error": "estrellas_invalidas"}`.

El panel del DJ recibe `rating: {avg, count}` en cada solicitud de `GET /dj/api/requests/`.

## 7. Formulario `POST /pedir/<venue_slug>/`

Campos (`application/x-www-form-urlencoded`, con `csrfmiddlewaretoken`):

| Campo | Obligatorio | Notas |
|---|---|---|
| `first_name`, `last_name` | Sí | |
| `alias` | No | |
| `phone` | Sí | 7–15 dígitos |
| `email` | Sí | Identidad del asistente |
| `venue` | Sí | ID de la discoteca |
| `title`, `artist` | Sí | |
| `genre` | Sí | Clave de `SongRequest.Genre` |
| `reference_url` | No | Solo YouTube / Spotify |

Resultados: `302 → /pedido/<id>/` (éxito) · `200` con errores de formulario · `200` con la página de límite alcanzado.

## 8. APIs externas

### Portadas de canciones (implementado) — [apps/songs/thumbnails.py](../apps/songs/thumbnails.py)

Al registrar una canción con link, el servidor obtiene la imagen de portada **sin API keys**:

| Plataforma | Cómo | Red |
|---|---|---|
| YouTube | Se extrae el ID del video (`watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`, `music.youtube.com`) y se arma `https://i.ytimg.com/vi/<id>/hqdefault.jpg` | Ninguna |
| Spotify | `GET https://open.spotify.com/oembed?url=<link>` → campo `thumbnail_url` | 1 petición, timeout 4 s |

- Se ejecuta **después** de guardar y fuera de la transacción: si falla (timeout, link privado, sin internet), la canción queda registrada sin portada.
- Solo se aceptan imágenes `https` de `*.ytimg.com`, `*.scdn.co` y `*.spotifycdn.com`.
- Las imágenes se cargan desde el CDN de YouTube/Spotify directamente en el navegador (`loading="lazy"`, `referrerpolicy="no-referrer"`); no se guardan en nuestro servidor.
- Rellenar portadas faltantes: `python manage.py fetch_thumbnails` (`--all` para recalcular todas).

### YouTube Data API v3 — estadísticas y recomendación (implementado)

- **Módulos:** [apps/songs/youtube.py](../apps/songs/youtube.py) (cliente), [apps/songs/analysis.py](../apps/songs/analysis.py) (reglas), `enrich_youtube()` en [services.py](../apps/songs/services.py).
- **Autenticación:** `YOUTUBE_API_KEY` (gratis). Crear en Google Cloud Console → *APIs y servicios* → habilitar **YouTube Data API v3** → *Credenciales* → *Crear clave de API*. Recomendado: restringir la key a esa API. En AWS va en Secrets Manager (`cronso-dplay/django:YOUTUBE_API_KEY`).
- **Endpoints usados y cuota** (10.000 unidades/día gratis):

| Endpoint | Para qué | Unidades |
|---|---|---|
| `videos.list` (`snippet,statistics,contentDetails`) | Vistas, likes, # comentarios, duración, título | 1 |
| `commentThreads.list` (`order=relevance`, máx. 100) | Comentarios más relevantes para el análisis | 1 |
| `search.list` (`type=video`, categoría Música) | Solo si la canción no trae link de YouTube | 100 |

  Con link: ~2 unidades por canción (≈ 5.000 canciones/día). Sin link: ~102 (≈ 95/día). Si se agota la cuota, la canción se registra igual, sin estos datos. Para ahorrar, `YOUTUBE_SEARCH_FALLBACK=0`.
- **Caché:** si el mismo video (o la misma canción buscada) se consultó hace menos de `YOUTUBE_CACHE_HOURS`, se reutiliza.
- **Segundo plano:** se ejecuta en un hilo tras registrar la canción (`ENRICH_ASYNC=1`); el usuario no espera.
- **Privacidad / políticas:** no se guarda el texto de los comentarios, solo el resultado agregado del análisis. Las estadísticas se pueden refrescar con `python manage.py refresh_youtube --all`.

#### Reglas de la recomendación ([analysis.py](../apps/songs/analysis.py))

Cada comentario pesa `1 + ln(1 + likes)`; se mide qué fracción del peso total menciona cada tema:

| Tema | Palabras clave (ejemplos, ES/EN) | Resultado |
|---|---|---|
| Energía ≥ 10 % | fuego, 🔥, temazo, perreo, drop, fiesta, bailar, banger, hype | Momento **Pico de la noche** + etiqueta "🔥 Alta energía" |
| Nostalgia ≥ 10 % | clásico, infancia, recuerdos, old school, throwback, "quién sigue…" | **Bloque de clásicos** + "📼 Clásico / nostalgia" |
| Calma ≥ 8 % (y mayor que energía) | relax, chill, triste, lento, romántico, despecho | **Warm-up o cierre** + "🌙 Ambiente tranquilo" |
| Cantar ≥ 5 % | coro, cantar, letra, himno, anthem | "🎤 Para cantar en coro" |
| Likes / vistas ≥ 4 % (≥ 2 %) | — | "❤️ Muy querida por el público" ("👍 Buena aceptación") |
| Vistas ≥ 100 M | — | "🌎 Éxito masivo" |
| Negativos > positivos | malo, aburrido, cringe, worst… | "⚖️ Opiniones divididas" |
| Minuto más mencionado (ej. `2:10`) | marcas de tiempo en los comentarios | "🎯 Destacado 2:10" |

Con menos de 15 comentarios se marca "pocos comentarios" (baja confianza). Los umbrales son heurísticos y se ajustan en `analysis.py`.

### Google Identity Services — inicio de sesión del público (implementado)

- **Módulos:** [apps/accounts/google.py](../apps/accounts/google.py) (verificación), [views.py](../apps/accounts/views.py), [session.py](../apps/accounts/session.py).
- **Librería:** `google-auth` (`id_token.verify_oauth2_token`); el botón carga `https://accounts.google.com/gsi/client` solo en `/entrar/`.
- **Credencial:** `GOOGLE_CLIENT_ID` (ID de cliente OAuth tipo *Aplicación web*). Es público; **no** hay secreto.
- **Permisos (scopes):** `openid email profile` → no requieren verificación de Google. Mientras la app esté en modo *Prueba*, solo entran los *usuarios de prueba* agregados en la consola.
- **Orígenes de JavaScript autorizados:** `http://localhost:8000`, `http://localhost` y el dominio HTTPS de producción.

### Integraciones futuras (documentar aquí al implementarlas)

| Integración | Para qué | Credenciales (en Secrets Manager) |
|---|---|---|
| Spotify Web API (*Client Credentials*) | Autocompletar canción/artista y validar el track | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` |
| Amazon SES | Enviar código de verificación al correo | Rol de tarea con `ses:SendEmail` |

Plantilla para documentar una nueva integración:

```markdown
### <Nombre del servicio>
- Propósito:
- Módulo: apps/<app>/clients/<servicio>.py
- Autenticación / variables de entorno:
- Endpoints usados:
- Límites de cuota y manejo de errores / timeouts:
- Pruebas (mocks):
```
