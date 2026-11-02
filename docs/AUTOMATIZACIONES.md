# Automatizaciones — Cronso Dplay

## 1. Docker

### Imagen ([Dockerfile](../Dockerfile))

- **Multi-stage**: la etapa `builder` compila *wheels*; la imagen final (`python:3.12-slim`) solo instala esos wheels → imagen pequeña, sin compiladores.
- Corre como usuario **`app`** sin privilegios.
- `collectstatic` se ejecuta en el *build* (estáticos comprimidos con hash).
- `HEALTHCHECK` contra `/health/`.
- Proceso: Gunicorn, 3 workers × 2 threads.

### Arranque ([scripts/entrypoint.sh](../scripts/entrypoint.sh))

1. Espera a que PostgreSQL acepte conexiones (máx. 60 s).
2. `migrate` y `setup_roles` (desactivable con `RUN_MIGRATIONS=0`, útil si se ejecutan migraciones como tarea aparte en ECS).
3. `ensure_admin`: crea el Admin si no existe (o asegura sus privilegios). El Dockerfile quita saltos de línea CRLF del script por si se editó en Windows.
4. Ejecuta el comando (`gunicorn` o `runserver`).

### Compose

| Archivo | Uso |
|---|---|
| `docker-compose.yml` | Servicios `db` (postgres:16-alpine con volumen `pgdata` y healthcheck) y `web` |
| `docker-compose.override.yml` | Desarrollo: `runserver`, `DEBUG=1`, código montado como volumen |

```bash
docker compose up --build                          # desarrollo
docker compose -f docker-compose.yml up -d --build # producción local / servidor único
docker compose logs -f web
docker compose exec web python manage.py <comando>
docker compose down            # detener (conserva datos)
docker compose down -v         # detener y BORRAR la base de datos
```

## 2. Comandos de gestión

| Comando | Descripción |
|---|---|
| `python manage.py setup_roles` | Crea/actualiza grupos **DJ** (ver y cambiar solicitudes, ver discotecas) y **Administrador** (todo sobre songs, venues y auth). Idempotente |
| `python manage.py create_dj <usuario> <clave> [--name "DJ X"]` | Crea un usuario DJ sin acceso a `/admin/` |
| `python manage.py fetch_thumbnails [--all]` | Obtiene las portadas de YouTube/Spotify que falten |
| `python manage.py refresh_youtube [--all] [--status pending\|played\|rejected\|all]` | Consulta YouTube para las solicitudes sin datos; `--all` actualiza vistas/likes de todas |
| `python manage.py ensure_admin` | Crea el Admin con `DJANGO_SUPERUSER_USERNAME/PASSWORD` si no existe; si existe, solo asegura sus privilegios (no cambia la contraseña). Corre en cada arranque |
| `python manage.py createsuperuser` | Crea un Admin |
| `python manage.py test` | Ejecuta las pruebas |

Para convertir un usuario en **Administrador** no superusuario: en `/admin/` → Usuarios → marcar *Es staff* y agregar al grupo *Administrador*.

## 3. CI/CD ([.github/workflows/ci.yml](../.github/workflows/ci.yml))

```
push / PR ─► test ─────────────► docker ─────► deploy (solo main y si está habilitado)
             · Postgres 16          · docker build   · OIDC → rol AWS
             · makemigrations --check                  · build & push a ECR
             · check --deploy                          · render task definition
             · manage.py test                          · update ECS service y esperar estabilidad
```

### Configuración del deploy en GitHub

| Tipo | Nombre | Ejemplo |
|---|---|---|
| Variable | `AWS_DEPLOY_ENABLED` | `true` |
| Variable | `AWS_REGION` | `us-east-1` |
| Variable | `ECR_REPOSITORY` | `cronso-dplay` |
| Variable | `ECS_CLUSTER` | `cronso-dplay` |
| Variable | `ECS_SERVICE` | `cronso-dplay-web` |
| Secreto | `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::<id>:role/github-deploy-cronso-dplay` |

Reemplazar `<ACCOUNT_ID>` y `<REGION>` en [infra/ecs-task-definition.json](../infra/ecs-task-definition.json).

### Migraciones en producción

Con varias tareas ECS, lo más seguro es poner `RUN_MIGRATIONS=0` en el servicio y ejecutar antes del deploy una tarea única:

```bash
aws ecs run-task --cluster cronso-dplay --launch-type FARGATE \
  --task-definition cronso-dplay-web \
  --overrides '{"containerOverrides":[{"name":"web","command":["python","manage.py","migrate","--noinput"]}]}' \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-ecs]}"
```

## 4. Tareas programadas sugeridas

| Tarea | Frecuencia | Implementación en AWS |
|---|---|---|
| `refresh_youtube --all --status pending` (actualizar vistas/likes) | Cada hora durante la noche | EventBridge Scheduler → ECS RunTask |
| Exportar solicitudes de la noche a CSV/S3 | Diario 6:00 a. m. | EventBridge Scheduler → ECS RunTask con un comando `export_night` |
| Anonimizar asistentes con más de 90 días | Semanal | EventBridge Scheduler → ECS RunTask |
| Snapshot manual de RDS antes de releases | En cada deploy a `main` | Paso adicional en GitHub Actions |

> Estas tareas aún no están implementadas; al crearlas, añadir el comando en `apps/<app>/management/commands/` y registrarlo en [MODULOS.md](MODULOS.md).

## 5. Checklist de puesta en producción

- [ ] `DJANGO_SECRET_KEY` larga y aleatoria en Secrets Manager
- [ ] `DJANGO_DEBUG=0`, `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` con el dominio real
- [ ] `PUBLIC_BASE_URL` con el dominio real **antes** de imprimir los QR
- [ ] ID de cliente de Google con el dominio HTTPS en *Orígenes autorizados* y la pantalla de consentimiento **publicada** ("En producción")
- [ ] `DJANGO_HSTS_SECONDS=31536000` una vez verificado HTTPS
- [ ] Contraseña del superusuario cambiada tras el primer arranque
- [ ] Alarmas de CloudWatch creadas ([ARQUITECTURA_AWS.md §5](ARQUITECTURA_AWS.md#5-observabilidad))
- [ ] Backups de RDS verificados con una restauración de prueba
