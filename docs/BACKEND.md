# Backend — Cronso Dplay

## 1. Principios

- **Monolito modular Django**: una app por dominio (`core`, `venues`, `songs`, `dj`).
- **Reglas de negocio en `services.py`**, no en vistas ni formularios. Las vistas validan entrada y llaman al servicio.
- **Configuración por variables de entorno** (12-factor), sin archivos de settings por entorno.
- **Dependencias mínimas**: Django, psycopg, gunicorn, whitenoise, segno. Sin Django REST Framework: la API es pequeña y se resuelve con `JsonResponse`.

## 2. Modelo de datos

```
┌──────────────┐ 1      N ┌────────────────────┐ N      1 ┌──────────────┐
│    Guest     │──────────│    SongRequest     │──────────│    Venue     │
│──────────────│          │────────────────────│          │──────────────│
│ email (único)│          │ title, artist      │          │ name (único) │
│ first_name   │          │ genre (choices)    │          │ slug (único) │
│ last_name    │          │ reference_url      │          │ city         │
│ alias        │          │ platform (auto)    │          │ is_active    │
│ phone        │          │ thumbnail_url      │          └──────────────┘
│ created_at   │          │ youtube_data (JSON)│
└──────────────┘          │ status             │
                          │ title_key/artist_key (normalizados)
                          │ created_at  (prioridad)
                          │ status_changed_at, handled_by → auth.User
                          └────────────────────┘
```

| Restricción / índice | Motivo |
|---|---|
| `Guest.email` único (guardado en minúsculas) | El correo es la identidad del asistente |
| `UniqueConstraint(guest, title_key, artist_key)` | Una persona no repite canción (también a nivel de BD) |
| `Index(venue, status, created_at)` | Consulta principal del panel DJ |
| `Index(client_ip, created_at)` + índice en `device_id` | Conteo rápido de los límites anti-abuso |
| `Venue` con `on_delete=PROTECT` | No se borran discotecas con historial |

**Estados de `SongRequest`**: `pending` (En cola) → `played` (Sonó) / `rejected` (No disponible). El DJ puede devolver a `pending`.

**Géneros**: Reggaetón, Dancehall, Reggae, Salsa, Merengue, Bachata, Vallenato, Champeta, Cumbia, Electrónica, House, Pop, Rock, Hip-Hop, Urbano, Crossover, Otro. Para añadir uno se edita `SongRequest.Genre` en [apps/songs/models.py](../apps/songs/models.py) (no requiere migración de datos, solo `makemigrations`).

### Eventos (`apps/events`)

| Modelo | Campos clave |
|---|---|
| `Event` | `name`, `code` (6 caracteres sin 0/O/1/I, único), `venue`, `dj`, `max_per_person` (1–20), `is_open`, `closed_at` |
| `SongRequest.event` | Evento al que pertenece el pedido (nulo = pedido por el QR de la discoteca) |
| `SongRequest.counts_toward_limit` | `False` cuando el DJ restablece el cupo: la canción sigue en la cola pero no cuenta |
| `LimitReset` | Historial: persona, evento, canciones liberadas, quién y cuándo |

**Géneros del evento** (`Event.allowed_genres`, lista de códigos de `SongRequest.Genre`; vacía = todos): el formulario del público solo ofrece esos géneros y muestra el aviso *"Esta noche el DJ toca: …"*; si llega otro género se rechaza con *"Este evento es solo de Reggaetón y Salsa…"*. `register_song_request()` también lo valida (`GenreNotAllowed`).

**Crear discoteca desde el evento:** `EventForm` acepta `new_venue=True` + `new_venue_name`/`new_venue_city`. Si ya existe una con el mismo nombre normalizado se reutiliza (no se duplica); `Venue.save()` agrega sufijo al slug si choca.

**Alcance del cupo** (`limit_scope()` en services.py): con evento, cuentan los pedidos de ese evento con `counts_toward_limit=True`; sin evento, los pedidos sin evento dentro de `SONG_LIMIT_WINDOW_HOURS`. En un evento, el cupo por persona **y** por dispositivo es `event.max_per_person`. La regla de no repetir canción también es por evento (restricciones únicas parciales: una para `event IS NULL` y otra por evento).

**Restablecer** (`reset_limit()`): marca `counts_toward_limit=False` en los pedidos de la persona **y de los dispositivos que usó**, dentro del alcance, y crea un `LimitReset`. El DJ ve el correo enmascarado (`el******@hotmail.com`) y nunca el celular.

### Calificación de la noche (`ExperienceRating`)

| Regla | Detalle |
|---|---|
| Qué se califica (1–5 ★) | `venue_stars` (siempre), `event_stars` (si el pedido es de un evento), `dj_stars` (si el evento tiene DJ: `event.dj`) |
| Cuándo | Al pedir la **última canción del cupo** (`needs_experience()`: usadas + 1 ≥ cupo). Con cupo 3 → la 3ra; con cupo del evento distinto, la última de ese cupo |
| Obligatorio | `register_song_request()` lanza `ExperienceRequired(campos)` si faltan estrellas; la canción **no** se crea. Se guarda en la misma transacción que la canción |
| Una vez | Una por persona y evento (`UniqueConstraint(guest, event)`); sin evento, una por local cada 12 h. Tras restablecer el cupo no se vuelve a pedir |
| Dónde se ve | Admin: resumen (promedios por local, evento y DJ) y tabla de eventos. DJ: "Mis eventos" (su promedio y el de cada evento). `/admin/` → Calificaciones de la noche |

### Puntuaciones (`SongRating`)

| Campo | Detalle |
|---|---|
| `song` → `SongRequest` | Canción puntuada |
| `device_id` | Cookie anónima del dispositivo. `UniqueConstraint(song, device_id)`: un voto por dispositivo |
| `stars` | 1 a 5 (`CheckConstraint` en la BD) |
| `client_ip` | Para auditoría (solo Admin) |

## 3. Reglas de negocio (`apps/songs/services.py`)

`register_song_request(guest_data, song_data)`:

1. Abre una transacción y obtiene/crea el `Guest` con **`select_for_update()`** → dos envíos simultáneos con el mismo correo se serializan y nunca se supera el límite.
2. Actualiza los datos de contacto con lo último que escribió la persona.
3. Si `pedidos >= SONG_MAX_PER_EMAIL` (dentro de la ventana `SONG_LIMIT_WINDOW_HOURS` si está activa) → `LimitReached`.
4. Límites anti-abuso: si el **dispositivo** ya usó `SONG_MAX_PER_DEVICE` → `LimitReached("device")`; si la **IP** llegó a `SONG_MAX_PER_IP` en las últimas `SONG_IP_WINDOW_HOURS` (y no está en `SONG_IP_ALLOWLIST`) → `LimitReached("ip")`.
5. Si ya pidió la misma canción (texto normalizado sin tildes/signos) → `DuplicateSong`.
6. Crea la `SongRequest` (con `client_ip` y `device_id`); `save()` calcula `platform` (YouTube/Spotify) y las claves normalizadas.
7. Ya fuera de la transacción, `attach_thumbnail()` obtiene la portada del link y `enrich_in_background()` consulta YouTube en un hilo (vistas, likes, duración, recomendación por comentarios; ver [API.md §7](API.md#7-apis-externas)) (ver [API.md §7](API.md#7-apis-externas)). Si falla, no afecta el pedido.

Validaciones del formulario ([apps/songs/forms.py](../apps/songs/forms.py)):

| Campo | Regla |
|---|---|
| Nombres / Apellidos | Obligatorios, se capitalizan |
| Alias | Opcional, máx. 40 |
| Celular | 7–15 dígitos; admite `+`, espacios, guiones, paréntesis |
| Correo | Email válido, minúsculas |
| Discoteca | Debe estar activa (si viene del QR va oculta y preseleccionada) |
| Link | Opcional; solo `youtube.com`, `youtu.be`, `spotify.com` (y subdominios) |

### Identidad del asistente

| Regla | Implementación |
|---|---|
| Mismo correo → mismos nombres, apellidos y alias | `identity_mismatches()` compara con `normalize_key` (sin tildes/mayúsculas/espacios). Si no coinciden → `IdentityMismatch(fields)` y el formulario marca esos campos |
| No revelar datos ajenos | El error dice *"No coincide con lo que registraste la primera vez"*, nunca muestra los datos registrados |
| Alias único entre correos | `Guest.alias_key` + `UniqueConstraint(alias_key) WHERE alias_key <> ''`. `alias_taken()` lo valida antes; si dos pedidos compiten, la BD lo garantiza → `AliasTaken` |
| Alias en blanco | Se mantiene el registrado. Si no tenía alias, puede agregarse uno libre |
| Celular | Se puede actualizar |
| Asistente conocido en el dispositivo | Nombres, apellidos, correo (y alias si tiene) se muestran bloqueados (`readonly`), con "¿No eres tú? Usar otro correo". El servidor valida igual aunque se manipule el HTML |

La creación del asistente usa un *savepoint* (`transaction.atomic()` anidado) para que un `IntegrityError` por carrera no invalide la transacción principal.

### Controles anti-abuso

| Control | Cómo se identifica | Límite por defecto | Mensaje al usuario |
|---|---|---|---|
| Correo | `Guest.email` | 3 (ventana `SONG_LIMIT_WINDOW_HOURS`) | Explica que ese correo ya pidió sus 3 canciones y ofrece "Usar otro correo" solo si el dispositivo aún tiene cupo |
| Dispositivo | Cookie firmada `dplay_device` (UUID aleatorio, `HttpOnly`, 2 años) — [apps/songs/device.py](../apps/songs/device.py) | 3 | Genérico: *"Ya alcanzaste el máximo de canciones que se pueden pedir por ahora"* |
| IP pública | [apps/core/net.py](../apps/core/net.py) `get_client_ip()` | 15 cada 12 h | El mismo mensaje genérico. **Nunca** se muestra la IP |

- **Por qué el tope por IP es alto:** todas las personas conectadas al WiFi de la discoteca salen a internet con la misma IP, y los operadores móviles usan CGNAT (una IP para miles de líneas). Un tope de 3 por IP bloquearía a gente legítima. Si se conoce la IP pública del WiFi del bar, se agrega a `SONG_IP_ALLOWLIST`.
- **Lectura segura de la IP:** con `TRUSTED_PROXY_COUNT=N` se toma la N-ésima IP desde el final de `X-Forwarded-For`, así un cliente no puede falsificarla enviando su propio header. Valores: `0` local (usa `REMOTE_ADDR`), `1` detrás de ALB o Nginx, `2` detrás de CloudFront + ALB.
- **Limitaciones conocidas:** la cookie de dispositivo se puede evadir con modo incógnito o borrando cookies; por eso existe el tope por IP como segunda barrera. No es un control infalible, sino disuasivo.
- **Visibilidad:** `client_ip` y `device_id` aparecen solo en `/admin/` (columna IP, búsqueda y exportación CSV). La API del DJ no los incluye.
- **En Docker local** todas las peticiones llegan con la IP del gateway de Docker (ej. `172.18.0.1`), así que localmente el tope por IP cuenta todo junto.

## 4. Inicio de sesión del público con Google (`apps/accounts`)

**Flujo** (Google Identity Services, sin *client secret*):

```
/entrar/ ── botón Google (popup) ──► Google devuelve un ID token (JWT) al navegador
        └─ fetch POST /auth/google/ {credential, next}  (con X-CSRFToken)
              └─ verify_credential(): firma con certificados de Google, aud = GOOGLE_CLIENT_ID,
                 iss = accounts.google.com, no expirado, email_verified
              └─ guest_from_google(): busca por google_sub, luego por correo (vincula perfiles
                 anteriores), o crea el perfil con nombre/apellido/foto de Google
              └─ login_guest(): rota la sesión (anti fijación) y guarda guest_id
```

| Regla | Detalle |
|---|---|
| Qué exige sesión | `/pedir/…`, `/e/<código>/`, `/pedido/<id>/`, `/mis-canciones/`, `/perfil/` (redirigen a `/entrar/?next=…`) y `POST /cola/<id>/calificar/` (401 JSON). La cola pública (`GET /cola/`) se puede ver sin sesión |
| Datos del formulario | Con sesión, **nombres y correo salen de Google** (los campos ni se muestran; lo que se envíe por POST se ignora). Solo se piden **alias** (fijo una vez elegido) y **celular** |
| Perfil `/perfil/` | Foto, nombre, correo; editar celular (y alias si aún no tiene); cupo disponible en cada **evento abierto**; historial |
| Cupos | No cambian: siguen siendo por evento (y por dispositivo/IP) |
| Activación | `GOOGLE_LOGIN_REQUIRED` (por defecto activo si hay `GOOGLE_CLIENT_ID`). Sin client ID la app funciona como antes |
| Cabecera COOP | `SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"`: el valor por defecto de Django bloquea la ventana emergente de Google |
| DJ/Admin | No cambia: siguen con usuario y contraseña en `/dj/login/` |

**Orígenes permitidos por Google:** solo `http://localhost[:puerto]` o dominios **HTTPS**. Una IP de red local (`http://192.168.x.x`) no funciona: para probar en el celular se necesita un túnel HTTPS o el dominio real.

## 5. Identidad del asistente sin Google (modo anterior)

- Tras pedir una canción o consultar "Mis canciones", el correo se guarda en la **sesión** (`guest_email`). Así:
  - el formulario se prellena en el siguiente pedido,
  - la página `/pedido/<id>/` solo la ve la sesión que hizo el pedido (otra sesión recibe 404),
  - "Mis canciones" muestra solo los pedidos de ese correo.
- "Salir" / "Usar otro correo" borra el correo de la sesión (útil si se presta el celular).
- ⚠️ Por diseño (requisito: el correo es el único filtro), cualquiera que escriba un correo ajeno vería **títulos de canciones** de ese correo, nunca datos personales. Si se requiere más privacidad, el siguiente paso es enviar un código de verificación al correo (ver backlog en [MODULOS.md](MODULOS.md)).

## 6. Perfiles y permisos

| Perfil | Implementación | Acceso |
|---|---|---|
| Asistente | Anónimo + sesión | `/`, `/pedir/…`, `/pedido/<id>/`, `/mis-canciones/` |
| DJ | Usuario Django en grupo **`DJ`**, `is_staff=False` | `/dj/` y `/dj/api/*`. Sin `/admin/` |
| Admin | `is_superuser`, o grupo **`Administrador`** + `is_staff=True` | Todo, incluido `/admin/` y `/v/<slug>/qr/` |

- **Acceso único** en `/acceso/` (`DjLoginView` + `StaffAuthenticationForm`): solo entran DJ, Admin o staff; el login propio del `/admin/` redirige aquí.
- Los grupos se crean con `python manage.py setup_roles` (idempotente, se ejecuta en cada arranque del contenedor).
- Decoradores en [apps/dj/permissions.py](../apps/dj/permissions.py): `dj_required` (HTML → redirige a login) y `dj_api_required` (JSON → 401/403).
- La serialización para el DJ ([apps/dj/serializers.py](../apps/dj/serializers.py)) expone `requester` (alias o nombre) y `requester_email`; **nunca** el celular. La cola pública no muestra correos.

## 7. Administración (`/admin/`)

- **Discotecas**: CRUD, slug automático, link "Imprimir QR".
- **Asistentes**: búsqueda por correo/nombre/celular, conteo de canciones, pedidos en línea.
- **Solicitudes**: filtros por estado, discoteca, género, plataforma y fecha; acciones *Marcar como sonada*, *Marcar como no disponible* y **Exportar a CSV** (compatible con Excel).

## 8. Configuración relevante

Ver tabla completa en el [README](../README.md#5-variables-de-entorno). Puntos clave de [config/settings.py](../config/settings.py):

- Sin `POSTGRES_HOST` → SQLite (solo para pruebas rápidas).
- `CONN_MAX_AGE` + `CONN_HEALTH_CHECKS` para reutilizar conexiones.
- Zona horaria `America/Bogota`, idioma `es-co`.
- WhiteNoise con `CompressedManifestStaticFilesStorage` en producción (archivos comprimidos y con hash).

## 9. Pruebas

```bash
python manage.py test
```

| Archivo | Cubre |
|---|---|
| [apps/songs/tests.py](../apps/songs/tests.py) | Portadas (formatos de link de YouTube, oEmbed de Spotify simulado, fallo de red, hosts no permitidos), límite de 3, correo sin mayúsculas, duplicados con tildes, detección de plataforma, flujo HTML completo, privacidad de "Mis canciones" y de la página de éxito |
| [apps/songs/tests.py](../apps/songs/tests.py) `AbuseLimitTests`, `ClientIpTests` | Límite por dispositivo con distintos correos, tope por IP con mensaje que no revela la IP, redes exentas, IP oculta al DJ, `X-Forwarded-For` falsificado |
| [apps/dj/tests.py](../apps/dj/tests.py) | 401/403 de la API, datos privados ocultos al DJ, cambio de estado, DJ sin acceso a `/admin/` |

## 10. Convenciones para nuevas apps

1. Crear en `apps/<nombre>/` con `apps.py` → `name = "apps.<nombre>"`.
2. Registrar en `INSTALLED_APPS` y, si tiene rutas, en `config/urls.py` con `app_name`.
3. Lógica de negocio en `services.py`, endpoints JSON documentados en [API.md](API.md).
4. Pruebas en `tests.py` y registro en [MODULOS.md](MODULOS.md).
