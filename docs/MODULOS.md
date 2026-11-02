# Registro de módulos — Cronso Dplay

> Documento **vivo**: cada vez que se cree una app, comando, endpoint o integración, se agrega aquí usando la plantilla del final.

## Índice

| App | Ruta base | Responsabilidad | Estado |
|---|---|---|---|
| `core` | `/`, `/health/` | Home, health check, datos globales de plantillas | ✅ v1 |
| `venues` | `/v/` | Discotecas/bares y códigos QR | ✅ v1 |
| `songs` | `/pedir/`, `/pedido/`, `/mis-canciones/` | Asistentes, solicitudes y reglas de negocio | ✅ v1 |
| `dj` | `/dj/` | Panel DJ, API JSON, permisos y roles, **límites** | ✅ v1 |
| `events` | `/e/`, `/dj/eventos/` | Eventos del DJ: link corto, QR, cupo por evento | ✅ v1 |
| `accounts` | `/entrar/`, `/perfil/` | Inicio de sesión del público con Google y perfil | ✅ v1 |
| `control` | `/control/` | Panel de control del Admin: resumen, usuarios DJ/Admin, personas, discotecas | ✅ v1 |

---

## core — `apps/core`

| Elemento | Archivo | Detalle |
|---|---|---|
| Vista `home` | `views.py` | Lista discotecas activas |
| Vista `health` | `views.py` | `SELECT 1` a la BD → 200/503 |
| `get_client_ip`, `ip_in_list` | `net.py` | IP pública real detrás de proxies; redes exentas (CIDR) |
| Context processor `app_info` | `context_processors.py` | `APP_NAME`, `SONG_MAX_PER_EMAIL`, `QUOTA_SLOTS` |

## venues — `apps/venues`

| Elemento | Archivo | Detalle |
|---|---|---|
| Modelo `Venue` | `models.py` | `name`, `slug` (auto), `city`, `is_active`; `public_url` = URL del QR |
| Vista `entry` | `views.py` | Destino del QR → redirige al formulario |
| Vista `qr_svg` | `views.py` | SVG con `segno`, corrección de errores alta |
| Vista `qr_print` | `views.py` | Página imprimible (staff) |
| Admin | `admin.py` | Link "Imprimir QR" |

## songs — `apps/songs`

| Elemento | Archivo | Detalle |
|---|---|---|
| Modelo `Guest` | `models.py` | Asistente identificado por correo |
| Modelo `SongRequest` | `models.py` | Canción, género, link, estado, prioridad por `created_at` |
| `register_song_request` | `services.py` | Límite por correo + duplicados, con bloqueo de fila |
| `identity_mismatches`, `alias_taken`, `IdentityMismatch`, `AliasTaken` | `services.py` | Identidad fija por correo y alias único |
| `remaining_for_email` | `services.py` | Cupo restante |
| `remaining`, `remaining_for_device`, `ip_limit_reached` | `services.py` | Cupo efectivo y límites anti-abuso |
| `get_device_id`, `set_device_cookie` | `device.py` | Cookie anónima firmada del dispositivo |
| `attach_thumbnail` | `services.py` | Guarda la portada tras crear la solicitud |
| `fetch_thumbnail`, `youtube_video_id` | `thumbnails.py` | Portada desde YouTube (por ID) o Spotify (oEmbed) |
| `youtube.py` | `youtube.py` | Cliente YouTube Data API v3: `video_details`, `top_comments`, `search_video` |
| `analyze` | `analysis.py` | Recomendación por reglas a partir de comentarios |
| `enrich_youtube`, `enrich_in_background` | `services.py` | Guarda estadísticas y recomendación (hilo, caché, nunca bloquea) |
| Comando `refresh_youtube` | `management/commands/` | Consulta/actualiza datos de YouTube |
| Comando `fetch_thumbnails` | `management/commands/` | Rellena portadas faltantes |
| Modelo `SongRating` | `models.py` | Estrellas 1–5, una por dispositivo y canción |
| Modelo `ExperienceRating` | `models.py` | Calificación de la noche (local, evento, DJ) en la última canción del cupo |
| `needs_experience`, `experience_targets`, `ExperienceRequired` | `services.py` | Cuándo pedirla, qué se califica y bloqueo si falta |
| `public_queue`, `rate_song`, `with_ratings` | `api.py` | Cola pública y votos (sin datos privados) |
| `SongRequestForm`, `EmailLookupForm` | `forms.py` | Validación de datos y links |
| Vistas | `views.py` | `request_song`, `success`, `my_requests`, `forget_me` |
| Admin | `admin.py` | Filtros, acciones de estado, exportar CSV |
| Pruebas | `tests.py` | 33 casos |

## control — `apps/control`

| Elemento | Archivo | Detalle |
|---|---|---|
| `is_platform_admin`, `admin_required` | `permissions.py` | Superusuario o grupo Administrador; un DJ ve "Solo para el Admin" (403) |
| `StaffCreateForm`, `StaffEditForm`, `StaffPasswordForm`, `apply_role` | `forms.py` | Crear DJ/Admin con validación de contraseña; rol DJ ↔ Admin |
| Vistas | `views.py` | `dashboard`, `staff_list/edit/password`, `people_list/export`, `person_detail/reset/delete`, `events` (crear), `event_edit`, `event_toggle`, `event_delete`, `event_reset` (reiniciar playlist), `venues`, `venue_toggle` |
| Formulario de evento compartido | `templates/events/_event_form_fields.html` + `_event_form_script.html` | Lo usan el DJ (`/dj/eventos/`) y el Admin (`/control/eventos/`) |
| Comando `ensure_admin` | `management/commands/` | Admin garantizado en cada arranque |
| Reglas | — | El Admin no puede quitarse su rol ni desactivarse; el superusuario siempre es Admin; eliminar una persona exige escribir su correo |
| Pruebas | `tests.py` | 18 casos |

## accounts — `apps/accounts`

| Elemento | Archivo | Detalle |
|---|---|---|
| `verify_credential` | `google.py` | Verifica el ID token de Google (firma, audiencia, emisor, correo verificado) |
| `current_guest`, `login_guest`, `logout_guest`, `guest_required` | `session.py` | Sesión del público y decorador que exige Google (HTML → redirige, JSON → 401) |
| `guest_from_google` | `views.py` | Crea o vincula el perfil (por `google_sub` o correo) |
| Vistas | `views.py` | `login_view`, `google_callback`, `logout_view`, `profile` |
| `ProfileForm` | `forms.py` | Celular editable, alias fijo una vez elegido |
| Campos en `Guest` | `songs/models.py` | `google_sub` (único), `picture_url` |
| Pruebas | `tests.py` | 13 casos (Google simulado) |

## events — `apps/events`

| Elemento | Archivo | Detalle |
|---|---|---|
| Modelo `Event` | `models.py` | Código corto legible, discoteca, cupo por persona, abierto/cerrado |
| `EventForm` | `forms.py` | Crear evento, géneros permitidos y opción de crear una discoteca nueva en el mismo paso |
| Vistas públicas | `views.py` | `entry` (formulario del evento, 410 si cerrado), `qr` (SVG/PNG, descarga) |
| Vistas DJ | `views.py` | `dj_playlist` (playlist del evento: reutiliza `dj/panel.html` con `data-fixed-event`), `dj_list` ("Mis eventos": solo los propios; el Admin va a `/control/eventos/`), `dj_detail` (compartir), `dj_toggle`, `dj_print` — un DJ no puede abrir eventos de otro DJ (404) |
| Pruebas | `tests.py` | 26 casos (eventos, géneros, discoteca nueva y restablecimiento de límites) |

## dj — `apps/dj`

| Elemento | Archivo | Detalle |
|---|---|---|
| Permisos | `permissions.py` | Grupos `DJ`/`Administrador`, decoradores `dj_required`, `dj_api_required` |
| Serializador | `serializers.py` | JSON de solicitud sin datos privados |
| Vistas | `views.py` | `DjLoginView`, `panel`, `api_requests`, `api_update_status`, `limits`, `reset_guest_limit` |
| `mask_email` | `serializers.py` | Correo parcialmente oculto para el DJ |
| Comandos | `management/commands/` | `setup_roles`, `create_dj` |
| Frontend | `static/js/dj-panel.js` | Cola en vivo |
| Pruebas | `tests.py` | 5 casos |

---

## Backlog sugerido

| Idea | App | Notas |
|---|---|---|
| Verificación del correo con código (SES) | `songs` | Evita que alguien use un correo ajeno |
| Botones "Buscar en Beatport / Beatsource / Bandcamp / TIDAL" | `dj` | Para conseguir la versión legal en WAV/FLAC/MP3 |
| Autocompletar desde Spotify | `songs` | Ver [API.md §7](API.md#7-apis-externas) |
| Votos ("yo también la quiero") | `songs` | Sube prioridad sin gastar cupo |
| "Noches"/eventos por discoteca | `venues` | Cupo por evento en vez de por ventana de horas |
| Notificaciones en tiempo real | `dj` | Django Channels + Redis |
| Rate limiting por IP | `core` | AWS WAF o middleware |

---

## Plantilla para un nuevo módulo

```markdown
## <nombre> — `apps/<nombre>`

**Propósito:** …
**Rutas:** `/…/`
**Depende de:** apps / servicios externos

| Elemento | Archivo | Detalle |
|---|---|---|
| Modelo … | models.py | … |
| Servicio … | services.py | … |
| Endpoint … | views.py | Documentado en API.md §… |
| Comando … | management/commands/… | … |

**Variables de entorno nuevas:** …
**Permisos / perfiles:** …
**Pruebas:** …
```
