# Arquitectura en AWS — Cronso Dplay

> Rol: Arquitecto de soluciones AWS. Objetivo: una arquitectura **simple, económica y segura**, adecuada para picos de tráfico nocturnos (cientos de personas escaneando el QR en pocos minutos) y fácil de operar por un equipo pequeño.

## 1. Vista general

```
                  Usuarios (celular / PC)
                           │ HTTPS
                           ▼
                 ┌───────────────────┐
   Route 53 ───► │    CloudFront     │  caché de /static/*, TLS (ACM), WAF opcional
                 └─────────┬─────────┘
                           │
              ┌────────────▼────────────┐  VPC 10.0.0.0/16
              │  Subredes públicas      │
              │  ┌───────────────────┐  │
              │  │ Application LB    │  │  health check: GET /health/
              │  └─────────┬─────────┘  │
              │  Subredes privadas      │
              │  ┌─────────▼─────────┐  │
              │  │ ECS Fargate       │  │  2 tareas (min) · auto scaling por CPU
              │  │ contenedor "web"  │  │  Gunicorn + WhiteNoise
              │  └─────────┬─────────┘  │
              │  ┌─────────▼─────────┐  │
              │  │ RDS PostgreSQL 16 │  │  Multi-AZ en prod · backups 7 días
              │  └───────────────────┘  │
              └─────────────────────────┘
   ECR (imágenes) · Secrets Manager (claves) · CloudWatch (logs, alarmas)
```

## 2. Componentes

| Servicio | Uso | Configuración sugerida |
|---|---|---|
| **Route 53** | DNS `dplay.cronso.com` | Registro alias a CloudFront |
| **ACM** | Certificado TLS | En `us-east-1` para CloudFront + en la región del ALB |
| **CloudFront** | CDN y terminación TLS | Comportamiento `/static/*` con caché 1 año (los archivos llevan hash por `CompressedManifestStaticFilesStorage`); resto sin caché, reenviando cookies y `Host` |
| **AWS WAF** (opcional) | Protección | Regla de *rate limiting* por IP sobre `POST /pedir/*` (ej. 30 req / 5 min) y reglas administradas comunes |
| **ALB** | Balanceo | Listener 443 → target group puerto 8000, health check `/health/` |
| **ECS Fargate** | Cómputo | Task 0.5 vCPU / 1 GB, mínimo 2 tareas en 2 AZ. Auto scaling objetivo CPU 60 % (máx. 6) |
| **ECR** | Registro de imágenes | *Scan on push* activado, política de ciclo de vida: conservar 20 imágenes |
| **RDS PostgreSQL 16** | Base de datos | `db.t4g.micro` (dev) / `db.t4g.small` Multi-AZ (prod), cifrado KMS, backups 7 días, *deletion protection* |
| **Secrets Manager** | Secretos | `cronso-dplay/django` (SECRET_KEY) y `cronso-dplay/rds` (credenciales con rotación) |
| **CloudWatch** | Observabilidad | Log group `/ecs/cronso-dplay` (retención 30 días), alarmas abajo |

¿Por qué Fargate y no Lambda o EC2? La app es un monolito Django con sesiones y conexiones persistentes a Postgres; Fargate evita administrar servidores y el *cold start* de Lambda, y escala por tarea. Para un solo local con muy poco tráfico, **App Runner** o una **Lightsail** con Docker Compose son alternativas aún más baratas (ver §7).

## 3. Red y seguridad

| Security Group | Entrada permitida |
|---|---|
| `sg-alb` | 443 desde Internet (o solo desde el prefijo administrado de CloudFront) |
| `sg-ecs` | 8000 solo desde `sg-alb` |
| `sg-rds` | 5432 solo desde `sg-ecs` |

- Las tareas ECS y RDS viven en **subredes privadas**. Salida a Internet por NAT Gateway (o **VPC endpoints** para ECR, Secrets Manager y CloudWatch Logs, que además ahorran costo de NAT).
- **IAM**:
  - *Execution role*: `AmazonECSTaskExecutionRolePolicy` + `secretsmanager:GetSecretValue` sobre los dos secretos.
  - *Task role*: sin permisos (la app no llama servicios AWS hoy).
  - *Deploy role* para GitHub Actions vía **OIDC** (sin llaves de acceso): `ecr:*` sobre el repositorio, `ecs:UpdateService`, `ecs:RegisterTaskDefinition`, `iam:PassRole` sobre los dos roles anteriores.
- Django en producción: `DEBUG=0`, cookies `Secure`, `SECURE_PROXY_SSL_HEADER` (TLS termina en CloudFront/ALB), HSTS configurable, CSRF en todos los formularios.
- **Google Sign-In:** agregar el dominio HTTPS (ej. `https://dplay.cronso.com`) a los *Orígenes de JavaScript autorizados* del ID de cliente OAuth; `GOOGLE_CLIENT_ID` va como variable de entorno (no es secreto).
- **IP del cliente:** CloudFront agrega la IP del visitante a `X-Forwarded-For` y el ALB agrega la del edge de CloudFront; por eso en ECS se usa `TRUSTED_PROXY_COUNT=2`. Si se quita CloudFront, cambiar a `1`.
- **Datos personales** (nombre, celular, correo, **IP pública** e identificador de dispositivo): solo los ve el perfil Admin. La API del DJ no los expone. Ver la política de retención en §6.

## 4. Escalado y rendimiento

- Cada tarea: Gunicorn con 3 *workers* × 2 *threads* ≈ 6 peticiones concurrentes. 2 tareas cubren cómodamente varios cientos de usuarios simultáneos para un formulario ligero.
- Estáticos servidos por CloudFront → el contenedor casi solo atiende HTML y JSON.
- `CONN_MAX_AGE=60` reutiliza conexiones a Postgres. Si se superan ~10 tareas, añadir **RDS Proxy**.
- El panel DJ consulta cada 8 s; con N DJs conectados son N/8 peticiones por segundo, insignificante. Si en el futuro se necesitan notificaciones instantáneas, migrar a WebSockets (Django Channels + ElastiCache Redis).
- El límite de 3 canciones es **consistente ante concurrencia**: se bloquea la fila del asistente (`SELECT … FOR UPDATE`) dentro de una transacción.

## 5. Observabilidad

| Alarma (CloudWatch) | Umbral | Acción |
|---|---|---|
| ALB `HTTPCode_Target_5XX_Count` | > 10 en 5 min | SNS → correo / Slack |
| ALB `UnHealthyHostCount` | ≥ 1 durante 3 min | SNS |
| ECS `CPUUtilization` | > 80 % 10 min | SNS (el auto scaling ya actúa a 60 %) |
| RDS `FreeStorageSpace` | < 2 GB | SNS |
| RDS `DatabaseConnections` | > 80 % del máximo | SNS |

Logs: Gunicorn escribe *access log* a stdout → CloudWatch Logs. Consultas útiles con Logs Insights:

```
fields @timestamp, @message | filter @message like /POST \/pedir/ | stats count() by bin(5m)
```

## 6. Backups, continuidad y retención

- RDS: snapshots automáticos 7 días + snapshot manual antes de cada migración mayor.
- RPO ≈ 5 min (PITR de RDS), RTO ≈ 30 min (restaurar instancia y actualizar el secreto `host`).
- Retención de datos personales sugerida: anonimizar asistentes, IPs y dispositivos con más de 90 días (ver tarea programada en [AUTOMATIZACIONES.md](AUTOMATIZACIONES.md)).

## 7. Costos estimados (us-east-1, referencia)

| Escenario | Componentes | Costo mensual aprox. |
|---|---|---|
| **Mínimo** (1 local) | Lightsail 2 GB con Docker Compose (Postgres en el mismo host) | ~10–12 USD |
| **Estándar** | Fargate 2×(0.5 vCPU/1 GB) + RDS t4g.micro + ALB + CloudFront | ~70–90 USD |
| **Producción HA** | + RDS Multi-AZ t4g.small + NAT Gateway + WAF | ~150–200 USD |

Ahorros: VPC endpoints en lugar de NAT, *Fargate Spot* para tareas extra, apagar entornos de prueba fuera de horario.

## 8. Entornos

| Entorno | Rama | Infra |
|---|---|---|
| `dev` | local | `docker compose up` |
| `staging` | `develop` | Fargate 1 tarea + RDS micro |
| `prod` | `main` | Arquitectura completa |

Se recomienda describir la infraestructura como código (Terraform o AWS CDK) en la carpeta `infra/`. Hoy existe la *task definition* base en [infra/ecs-task-definition.json](../infra/ecs-task-definition.json).
