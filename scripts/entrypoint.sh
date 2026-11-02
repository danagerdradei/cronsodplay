#!/bin/sh
# Punto de entrada del contenedor: espera la BD, migra, crea roles y arranca.
set -e

if [ -n "$POSTGRES_HOST" ]; then
  echo "Esperando PostgreSQL en $POSTGRES_HOST:${POSTGRES_PORT:-5432}..."
  python - <<'EOF'
import os, socket, time
host, port = os.environ["POSTGRES_HOST"], int(os.environ.get("POSTGRES_PORT", 5432))
for _ in range(60):
    try:
        socket.create_connection((host, port), timeout=2).close()
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("PostgreSQL no respondió a tiempo")
EOF
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py setup_roles
fi

# Crea el Admin de la plataforma si no existe (o asegura sus privilegios). Idempotente.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py ensure_admin
fi

exec "$@"
