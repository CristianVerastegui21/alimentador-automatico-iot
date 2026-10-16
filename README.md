# Alimentador IoT — versión para GitHub y Render

Proyecto basado en el archivo RAR compartido: conserva HTML/CSS/JS del dashboard, rutas Flask, Wokwi ESP32, OLED, HC-SR04 y servo. Esta entrega **no incluye credenciales ni la base SQLite original**.

## 1. Supabase (OBLIGATORIO ANTES DE ARRANCAR)

1. Abre tu proyecto en Supabase → SQL Editor.
2. Ejecuta `sql/01_supabase.sql` completo. **Antes de hacerlo**, verifica si ya tienes órdenes `pendiente` o `procesando` duplicadas; el índice único fallará si hay varias órdenes activas por dispositivo. No elimines órdenes a ciegas.
3. Debe existir el dispositivo `ESP32-001` en `dispositivos`.
4. En Settings → API Keys, utiliza una **secret/service_role key exclusivamente en Flask/Render**. Nunca la pongas en el frontend ni en firmware. El SQL habilita RLS; la clave de servidor debe disponer de permisos para las tablas y RPC.
5. Si tu esquema ya difiere del SQL suministrado, haz copia de seguridad y concilia columnas antes de ejecutarlo.

## 2. Ejecución local (Windows / VS Code)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edita `.env` y completa `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SUPABASE_URL`, `SUPABASE_KEY`, `DEVICE_TOKEN`. Genera secretos con `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Para desarrollo local deja `COOKIE_SECURE=0`.

```powershell
python run.py
python -m unittest discover -s tests -v
```

Abre `http://127.0.0.1:5000` y accede con `ADMIN_EMAIL` / `ADMIN_PASSWORD`. **El login ya no depende de SQLite**: se valida contra variables de entorno. Es un único administrador; cambia las claves antes de publicar. El `ADMIN_PASSWORD` debe ser fuerte.

## 3. GitHub

Sube el contenido de esta carpeta a un repositorio, preferentemente privado. `.gitignore` excluye `.env`, `.venv`, `instance`, `*.db`. **No subas el RAR original**, porque contiene credenciales y una base de datos. Rota las credenciales compartidas anteriormente antes de usar Render.

```powershell
git init
git add .
git status
git commit -m "Alimentador IoT Flask Supabase Wokwi"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/TU-REPO.git
git push -u origin main
```

## 4. Render

Usa `render.yaml` como Blueprint o crea un Web Service Python manual:

- Build: `pip install -r requirements.txt`
- Start: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --timeout 90`
- Variables: `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `SUPABASE_URL`, `SUPABASE_KEY`, `DEVICE_TOKEN`, `DEVICE_CODE=ESP32-001`, `COOKIE_SECURE=1`, `FLASK_DEBUG=0`.
- No configures `AUTH_DATABASE_URL` ni `DATABASE_URL`; el proyecto usa Supabase REST.
- Visita `https://TU-SERVICIO.onrender.com/health` y luego `/login`.

## 5. Wokwi

Abre Wokwi con `firmware/sketch.ino`, `firmware/diagram.json`, `firmware/libraries.txt`. Sustituye en `sketch.ino` los marcadores `API_BASE` y `DEVICE_TOKEN` por URL de Render y token de servidor; **no uses el token Supabase**. El firmware usa `WiFiClientSecure::setInsecure()` solo para simulación. La programación se sincroniza cada 60 s, se guarda en Preferences/NVS y se ejecuta localmente incluso si se pierde Internet, siempre que el reloj NTP ya se haya sincronizado. En Wokwi, la persistencia de NVS entre sesiones depende de cómo se reinicie la simulación.

**Importante**: al ejecutar el servo, calibra tiempo de apertura y cantidad de alimento; HC-SR04 estima porcentaje, no peso. En hardware físico alimenta el servo separadamente y protege el pin ECHO (5V).

## 6. API

- `GET /health` (público)
- `POST /login`, `POST /logout`, `GET /` (sesión)
- `GET /api/status`, `POST /api/feed`, `POST /api/schedules`, `PATCH/DELETE /api/schedules/<id>` (sesión, CSRF para escritura)
- `GET /api/device/config`, `GET /api/device/command`, `POST /api/device/ack`, `POST /api/device/telemetry`, `POST /api/device/event` (`X-Device-Token`)

La RPC de encolado utiliza índice único de órdenes activas. La RPC de toma utiliza bloqueo `FOR UPDATE SKIP LOCKED`. Las órdenes en `procesando` **no se reintentan automáticamente**: si el ACK se pierde, revisa físicamente el dispensador antes de decidir qué hacer. El historial automático usa `completed/failed`, el manual usa `completado/fallido` según el esquema original.

## 7. Alcance y limitaciones

- Diseñado para **un dispositivo** y **un administrador**; no incluye recuperación de contraseña ni MFA.
- La autenticación por variables de entorno funciona en Render sin SQLite, pero para un producto real conviene usar Supabase Auth.
- No se han realizado pruebas con Render, una instancia real de Supabase ni el hardware físico desde este entorno. Verifica todo con tu cuenta antes de usarlo para alimentar mascotas sin supervisión.
- `/health` solo comprueba que Flask responde, no que Supabase esté disponible. UptimeRobot no garantiza servicio permanente.
