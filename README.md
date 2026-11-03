# 🎧 Cronso Dplay

Web app para que las personas de una discoteca o bar **le pidan canciones al DJ** escaneando un código QR, desde cualquier celular o PC, sin crear usuario ni contraseña.

| | |
|---|---|
| **Stack** | Python 3.12 · Django 5.2 · PostgreSQL 16 · Gunicorn · WhiteNoise |
| **Frontend** | Plantillas Django + CSS propio + JS vanilla (sin frameworks, CSS + JS ~18 KB) |
| **Infraestructura** | Docker / Docker Compose → AWS (ECS Fargate + RDS + ALB + CloudFront) |
| **CI/CD** | GitHub Actions (pruebas → build → deploy a ECS) |

---

## 1. Funcionalidad

### Perfiles

| Perfil | Cómo entra | Qué puede hacer |
|---|---|---|
| **Asistente** (persona que escanea el QR) | **Botón "Continuar con Google"** (`/entrar/`) cuando `GOOGLE_CLIENT_ID` está configurado; el perfil se crea solo con su nombre, correo y foto de Google. Sin esa variable, se identifica con su correo como antes | Pedir hasta **3 canciones por correo** y ver *solo* las canciones pedidas con su correo |
| **DJ** | Usuario y contraseña en `/dj/login/` | Ver la cola en vivo: canción, artista, género, link, portada, **vistas, likes y duración de YouTube, recomendación de en qué momento ponerla (según los comentarios)**, **quién la pidió (alias o nombre) y su correo** y **a qué hora**, en orden de llegada. Marcar como *sonó* / *no disponible* o eliminar. **No** ve el celular, ni entra a `/admin/` |
| **DJ – Mis eventos** | `/dj/eventos/` (solo sus eventos; la administración completa es del Admin). Cada evento tiene su **🎵 Playlist** en `/dj/eventos/<código>/playlist/` | Crear eventos (nombre, discoteca —o crear una nueva ahí mismo—, canciones por persona y **géneros de la noche**: el público solo puede pedir esos géneros); cada uno genera **link corto** `/e/<código>/` y **QR** (PNG/SVG/imprimible) para compartir por WhatsApp o copiar. Cerrar/reabrir eventos. El cupo se cuenta **por evento** |
| **DJ – Límites** | `/dj/limites/` | Buscar por correo, nombre o alias y **restablecer el cupo** de una persona (sus canciones siguen en la cola). Correo enmascarado, historial de restablecimientos |
| **Admin – Panel de control** | `/control/` (entra por `/acceso/`) | Resumen de la plataforma (cifras, canciones y géneros más pedidos, quién pide más, últimos pedidos); **crear y gestionar usuarios DJ y Admin** (rol, activar/desactivar, contraseña); **personas** con correo y celular completos (buscar, detalle, restablecer cupo, eliminar, exportar CSV); **eventos** (crear, editar, abrir/cerrar, eliminar y **reiniciar la playlist** de un evento); **discotecas** (crear, activar/desactivar, QR) |
| **Admin** | Superusuario o grupo *Administrador* con `is_staff` | Acceso a todo: `/admin/`, panel DJ, discotecas, asistentes, exportar CSV, imprimir QR |

### Reglas de negocio

- Datos obligatorios del asistente: **Nombres, Apellidos, Celular, Correo, Discoteca/Bar**. **Alias** es opcional.
- Datos de la canción: **Nombre de la canción, Artista, Género** (obligatorios) y **link de YouTube o Spotify** (opcional, se validan solo esos dominios).
- Máximo **3 canciones por correo** (configurable con `SONG_MAX_PER_EMAIL`). Al llegar al límite se muestra un mensaje amable: *"¡Gracias por tu buena energía! Ya pediste tus 3 canciones…"*.
- **Anti-abuso** (invisible para el usuario):
  - Máximo **3 canciones por dispositivo** (cookie anónima), aunque se cambie de correo.
  - Tope **por IP pública** alto y configurable (15 cada 12 h por defecto). No es 3 porque el WiFi del bar y los operadores móviles comparten la misma IP entre muchas personas. Se pueden eximir IPs/redes (ej. el WiFi de la discoteca).
  - La IP y el dispositivo **solo los ve el Admin**. Al usuario se le muestra un mensaje amable que no revela el motivo.
- **Calificación de la noche:** al pedir la **última canción de su cupo** (la 3ra con cupo 3), la persona debe calificar de 1 a 5 ★ el **local**, el **evento** y al **DJ**; sin eso no se envía. Se guarda por evento y local, una sola vez por evento.
- **En un evento no se repiten canciones**, sin importar quién la pida: se compara sin tildes, mayúsculas, signos ni artículos y en cualquier orden (`"La Kelly / El cartel de santa"` = `"Cartel de Santa / la kelly"`), y también por el mismo video de YouTube o track de Spotify.
- El correo no distingue mayúsculas (`ANA@x.com` = `ana@x.com`).
- **Identidad fija por correo:** los nombres, apellidos y alias con que se registró un correo la primera vez deben usarse igual en los siguientes pedidos (sin importar mayúsculas, tildes ni espacios). El celular sí se puede actualizar. Un alias en blanco significa "seguir con el registrado".
- **Alias único:** un alias pertenece a un solo correo. Los nombres sí pueden repetirse entre personas distintas.
- Opcional: `SONG_LIMIT_WINDOW_HOURS=12` reinicia el cupo cada 12 h (por noche). Por defecto `0` = nunca se reinicia.
- La prioridad de la cola es el **orden de registro** (el primero que pidió, primero en la lista).

### Flujo

```
QR en la mesa ──► /v/<discoteca>/ ──► /pedir/<discoteca>/ ──► formulario
                                                              │
                         ┌────────────── ¿>= 3 pedidos? ◄─────┘
                         │ sí                     │ no
                         ▼                        ▼
                "Límite alcanzado"        guarda ──► /pedido/<id>/ (posición en la cola)
                                                    │
                                    Panel DJ (/dj/) se actualiza cada 8 s
```

---

## 2. Inicio rápido

### Con Docker (recomendado)

```bash
cp .env.example .env            # ajustar claves
docker compose up --build       # desarrollo (recarga en caliente, DEBUG=1)
# o producción local:
docker compose -f docker-compose.yml up -d --build
```

Al arrancar, el contenedor **espera a PostgreSQL, migra, crea los grupos DJ/Administrador y el superusuario** definido en `.env`.

Luego:

1. Entra a <http://localhost:8000/admin/> con el usuario de `DJANGO_SUPERUSER_*`.
2. Crea una **Discoteca / Bar** → en el listado aparece el link **"Imprimir QR"**.
3. Crea el usuario del DJ:
   ```bash
   docker compose exec web python manage.py create_dj dj_nombre "Contraseña123" --name "DJ Nombre"
   ```
4. El DJ (y el Admin) entran por el acceso único <http://localhost:8000/acceso/>.

### Sin Docker

```bash
python -m venv .venv && .venv\Scripts\activate        # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
# Sin POSTGRES_HOST se usa SQLite; para Postgres exporta las variables de .env.example
python manage.py migrate && python manage.py setup_roles && python manage.py createsuperuser
python manage.py runserver
```

### Pruebas

```bash
python manage.py test                                   # local
docker compose exec web python manage.py test           # contra PostgreSQL
```

---

## 3. Estructura del proyecto

```
CronsoDplay/
├── config/                      # Proyecto Django
│   ├── settings.py              # Configuración (todo por variables de entorno)
│   ├── urls.py                  # Enrutador raíz
│   └── wsgi.py / asgi.py
├── apps/
│   ├── core/                    # Home, health check, context processor global
│   ├── venues/                  # Discotecas/Bares + generación de QR (SVG)
│   ├── songs/                   # Asistentes, solicitudes, reglas de negocio (services.py)
│   ├── events/                  # Eventos del DJ: link corto + QR, cupo por evento
│   ├── accounts/                # "Continuar con Google" para el público, perfil
│   ├── control/                 # Panel de control del Admin (/control/)
│   └── dj/                      # Panel DJ, API JSON, permisos y comandos de roles
├── templates/                   # Plantillas HTML (base + por app + partials)
├── static/
│   ├── css/app.css              # Único CSS (mobile-first, tema oscuro neón)
│   ├── js/dj-panel.js           # Único JS (cola en vivo del DJ)
│   └── img/                 # Logo Cronso (original + versiones WebP optimizadas)
├── scripts/entrypoint.sh        # Arranque del contenedor
├── infra/ecs-task-definition.json
├── .github/workflows/ci.yml     # CI/CD
├── docs/                        # Documentación por área (ver abajo)
├── Dockerfile                   # Multi-stage, usuario sin privilegios
├── docker-compose.yml           # db + web (producción)
├── docker-compose.override.yml  # Overrides de desarrollo
├── .env.example
└── requirements.txt             # Solo 5 dependencias
```

---

## 4. Documentación

| Documento | Contenido |
|---|---|
| [docs/ARQUITECTURA_AWS.md](docs/ARQUITECTURA_AWS.md) | Arquitectura en AWS, red, seguridad, costos, escalado, backups |
| [docs/BACKEND.md](docs/BACKEND.md) | Modelos, reglas de negocio, permisos, configuración |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Diseño, responsive, componentes, rendimiento |
| [docs/API.md](docs/API.md) | Endpoints JSON y rutas HTML con ejemplos |
| [docs/AUTOMATIZACIONES.md](docs/AUTOMATIZACIONES.md) | Docker, CI/CD, comandos de gestión, tareas programadas |
| [docs/MODULOS.md](docs/MODULOS.md) | **Registro vivo** de apps/módulos y plantilla para documentar nuevos |

---

## 5. Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | Clave secreta (obligatoria en producción) |
| `DJANGO_DEBUG` | `0` | `1` solo en desarrollo |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Dominios permitidos, separados por coma |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | Orígenes HTTPS, ej. `https://dplay.cronso.com` |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | — | Conexión a PostgreSQL. Sin `POSTGRES_HOST` usa SQLite |
| `DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD` | — | Admin creado al arrancar el contenedor |
| `SONG_MAX_PER_EMAIL` | `3` | Canciones máximas por correo |
| `SONG_LIMIT_WINDOW_HOURS` | `0` | Ventana del límite en horas (`0` = permanente) |
| `SONG_MAX_PER_DEVICE` | `3` | Canciones máximas por dispositivo (`0` = sin límite) |
| `SONG_MAX_PER_IP` | `15` | Tope por IP pública en la ventana (`0` = sin límite) |
| `SONG_IP_WINDOW_HOURS` | `12` | Ventana del tope por IP |
| `SONG_IP_ALLOWLIST` | — | IPs/CIDR exentas del tope por IP, separadas por coma |
| `TRUSTED_PROXY_COUNT` | `0` | Proxies delante de la app para leer la IP real (`2` con CloudFront + ALB) |
| `GOOGLE_CLIENT_ID` | — | ID de cliente OAuth (Web) para "Continuar con Google". Sin él, no se exige Google |
| `GOOGLE_LOGIN_REQUIRED` | `1` si hay client ID | Exigir Google para pedir canciones y puntuar |
| `YOUTUBE_API_KEY` | — | Key gratis de YouTube Data API v3 (vistas, likes, recomendación). Sin ella se omite |
| `YOUTUBE_SEARCH_FALLBACK` | `1` | Buscar el video si la canción no trae link de YouTube (100 unidades de cuota) |
| `YOUTUBE_COMMENTS_MAX` | `100` | Comentarios analizados por video |
| `YOUTUBE_CACHE_HOURS` | `24` | Reutilizar datos del mismo video |
| `ENRICH_ASYNC` | `1` | Consultar YouTube en segundo plano |
| `DJ_PANEL_POLL_SECONDS` | `8` | Frecuencia de refresco del panel DJ |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL que se codifica en el QR |
