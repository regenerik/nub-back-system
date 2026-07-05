# NUB System - Backend

Backend Flask para NUB System, preparado para datos reales en SQL con SQLAlchemy.

## Stack

- Python Flask
- SQLAlchemy
- Flask-Migrate / Alembic
- Flask-CORS
- JWT con Flask-JWT-Extended
- Flask-SocketIO para comunicacion live
- SQLite en desarrollo y PostgreSQL en produccion mediante `DATABASE_URL`
- Cloudinary preparado para imagenes

## Instalacion

Requiere Python 3.11 o superior.

```bash
python -m venv myenv
myenv\Scripts\activate
pip install -r requirements.txt
```

## Variables de entorno

Copiar `.env.example` a `.env` y ajustar valores:

```bash
copy .env.example .env
```

Para subida de imagenes con Cloudinary configurar en el backend:

```env
CLOUDINARY_CLOUD_NAME=tu_cloud_name
CLOUDINARY_API_KEY=tu_api_key
CLOUDINARY_API_SECRET=tu_api_secret
CLOUDINARY_FOLDER_NAME=nub-system
```

El frontend no debe tener `CLOUDINARY_API_SECRET`.

Para Auth0 con frontend estatico:

```env
AUTH0_DOMAIN=dev-1a67u9mz.us.auth0.com
AUTH0_CLIENT_ID=MRrsVJYMkQ7hK5LCVGTvfyR1ereHvoQZ
```

El backend recibe el `id_token` del static frontend en `POST /api/auth/auth0`, valida firma/issuer/audience con JWKS de Auth0 y emite el JWT interno de NUB.

## Comandos

```bash
flask --app wsgi.py db init
flask --app wsgi.py db migrate -m "initial schema"
flask --app wsgi.py db upgrade
flask --app wsgi.py seed
python run.py
```

Si ya tenias la base local creada antes de estas mejoras, ejecutar:

```powershell
flask --app wsgi.py db upgrade
```

Para iniciar manualmente en Windows desde cero:

```powershell
cd C:\Users\regen\Documents\Codex\2026-07-01\te\nub-back-system
myenv\Scripts\activate
python run.py
```

Si la base local no esta creada o se borro:

```powershell
cd C:\Users\regen\Documents\Codex\2026-07-01\te\nub-back-system
myenv\Scripts\activate
flask --app wsgi.py db upgrade
flask --app wsgi.py seed
python run.py
```

Healthcheck:

```bash
curl http://localhost:5000/api/health
```

## Estructura

- `app/modules/auth`: autenticacion, login, JWT y OAuth.
- `app/modules/users`: usuarios, roles y permisos.
- `app/modules/branches`: sucursales / barberias.
- `app/modules/clients`: clientes.
- `app/modules/barbers`: barberos y disponibilidad.
- `app/modules/appointments`: turnos y control de concurrencia.
- `app/modules/services`: servicios.
- `app/modules/products`: productos.
- `app/modules/sales`: ventas.
- `app/modules/payments`: cobros y medios de pago.
- `app/modules/inventory`: stock y movimientos.
- `app/modules/expenses`: gastos.
- `app/modules/salaries`: sueldos de barberos.
- `app/modules/stats`: dashboards y exportaciones.
- `app/modules/backups`: backup y restauracion.
- `app/modules/uploads`: subida de imagenes a Cloudinary.
- `app/socket_events.py`: conexion Socket.IO y salas live.
- `app/live.py`: helpers para emitir eventos de dominio.

## Seguridad base

- Passwords hasheados con Werkzeug.
- Sesiones JWT.
- Roles y permisos validados en backend.
- Secretos solo por variables de entorno.
- Endpoints admin separados y protegidos.

## Socket.IO

Socket.IO esta preparado para notificar cambios de agenda, ventas, pagos, stock y estadisticas a paneles abiertos. Para autenticar la conexion, enviar el JWT en el handshake:

```js
io(BACKEND_URL, { auth: { token } })
```

Eventos previstos:

- `appointment:created`
- `appointment:updated`
- `appointment:rescheduled`
- `appointment:cancelled`
- `appointment:completed`
- `sale:created`
- `sale:paid`
- `stock:updated`
- `stats:updated`

Salas previstas:

- `role:admin`
- `role:recepcion`
- `barber:{barber_id}`
- `branch:{branch_id}`
- `client:{client_id}`

Socket.IO no es la fuente de consistencia. Las validaciones, transacciones y constraints deben vivir en SQLAlchemy y la base de datos.

## Endpoints principales

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/register-client`
- `POST /api/auth/google`
- `POST /api/auth/auth0`
- `GET /api/auth/me`
- `GET /api/client/me/profile`
- `PATCH /api/client/me/profile`
- `GET /api/public/branches`
- `GET /api/public/services`
- `GET /api/public/barbers`
- `GET /api/public/availability`
- `POST /api/public/appointments`
- `GET /api/admin/users`
- `GET /api/admin/branches`
- `GET /api/admin/stats/overview`
- `GET /api/admin/backup/full`
- `GET /api/appointments`
- `POST /api/appointments`
- `POST /api/sales`
- `POST /api/uploads/image`

## Deploy en Render

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
python run.py
```

Configurar `DATABASE_URL`, `JWT_SECRET_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`, `SOCKET_CORS_ORIGINS`, `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID` y credenciales de Cloudinary desde el panel de Render.

Ejemplo de origenes cuando el frontend esta en Render Static:

```env
FRONTEND_URL=https://TU-FRONTEND.onrender.com
CORS_ORIGINS=https://TU-FRONTEND.onrender.com,http://localhost:4017,http://127.0.0.1:4017
SOCKET_CORS_ORIGINS=https://TU-FRONTEND.onrender.com,http://localhost:4017,http://127.0.0.1:4017
```

La base principal debe ser SQL. Google Sheets no se usa como base de datos principal en esta version.
