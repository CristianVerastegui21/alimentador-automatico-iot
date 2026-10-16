
import os
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import (
    Blueprint, request, jsonify, render_template,
    redirect, url_for, session, flash, abort
)
from werkzeug.security import check_password_hash, generate_password_hash
from functools import lru_cache

from .services.supabase_service import obtener_supabase


bp = Blueprint("main", __name__)

DEVICE_CODE = os.getenv("DEVICE_CODE", "ESP32-001")

@lru_cache(maxsize=4)
def admin_hash(password):
    return generate_password_hash(password)


# =====================================
# AUTENTICACION
# =====================================

def auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify(error="No autorizado"), 401

            return redirect(url_for("main.login"))

        return fn(*args, **kwargs)

    return wrapped


def device_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = os.getenv("DEVICE_TOKEN")

        if not token:
            return jsonify(
                error="Dispositivo no configurado"
            ), 503

        supplied = request.headers.get(
            "X-Device-Token", ""
        )

        if not secrets.compare_digest(supplied, token):
            return jsonify(error="Token inválido"), 401

        return fn(*args, **kwargs)

    return wrapped


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        supplied = request.headers.get(
            "X-CSRF-Token", ""
        )

        expected = session.get("csrf", "")

        if not expected or not secrets.compare_digest(
            supplied, expected
        ):
            return jsonify(error="CSRF inválido"), 403

        return fn(*args, **kwargs)

    return wrapped


# =====================================
# UTILIDADES SUPABASE
# =====================================

def supabase():
    return obtener_supabase()


def get_device():
    response = (
        supabase()
        .table("dispositivos")
        .select("*")
        .eq("codigo", DEVICE_CODE)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "No existe el dispositivo ESP32-001 en Supabase"
        )

    return response.data[0]


def get_device_id():
    return get_device()["id"]


def parse_datetime(value):
    if not value:
        return None

    dt = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def format_hour(value):
    return str(value or "00:00")[:5]


def db_error(error):
    print("Error Supabase:", type(error).__name__)

    return jsonify(
        error="No se pudo completar la operación"
    ), 503


# =====================================
# HEALTH
# =====================================

@bp.route("/health")
def health():
    return jsonify(status="ok")


# =====================================
# LOGIN LOCAL TEMPORAL
# =====================================

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        expected_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        expected_password = os.getenv("ADMIN_PASSWORD", "")
        if expected_email and expected_password and secrets.compare_digest(email, expected_email) and check_password_hash(admin_hash(expected_password), password):
            session.clear()
            session["user_id"] = expected_email
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("main.index"))

        flash("Credenciales incorrectas")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@auth_required
def logout():
    supplied = request.form.get("csrf", "")
    expected = session.get("csrf", "")

    if not expected or not secrets.compare_digest(
        supplied, expected
    ):
        abort(403)

    session.clear()

    return redirect(
        url_for("main.login")
    )


@bp.route("/")
@auth_required
def index():
    return render_template(
        "dashboard.html",
        csrf=session["csrf"]
    )


# =====================================
# DASHBOARD
# =====================================

@bp.route("/api/status")
@auth_required
def status():
    try:
        client = supabase()
        device = get_device()
        device_id = device["id"]

        schedules_data = (
            client.table("horarios")
            .select("*")
            .eq("dispositivo_id", device_id)
            .order("hora")
            .execute()
            .data
        )

        commands_data = (
            client.table("ordenes")
            .select("*")
            .eq("dispositivo_id", device_id)
            .order("id", desc=True)
            .limit(5)
            .execute()
            .data
        )

        history_data = (
            client.table("historial")
            .select("*")
            .eq("dispositivo_id", device_id)
            .order("id", desc=True)
            .limit(20)
            .execute()
            .data
        )

        last_seen = parse_datetime(
            device.get("ultima_conexion")
        )

        online = bool(
            last_seen and
            datetime.now(timezone.utc) - last_seen
            < timedelta(seconds=35)
        )

        schedules = [
            {
                "id": s["id"],
                "hour": format_hour(s["hora"]),
                "label": s["nombre"],
                "enabled": s["activo"]
            }
            for s in schedules_data
        ]

        commands = [
            {
                "id": c["id"],
                "status": c["estado"],
                "created_at": c["creado_en"]
            }
            for c in commands_data
        ]

        history = [
            {
                "id": h["id"],
                "source": h["tipo"],
                "status": h["resultado"],
                "description": "",
                "time": h["fecha"]
            }
            for h in history_data
        ]

        return jsonify(
            device={
                "online": online,
                "level": device.get(
                    "nivel_alimento"
                ),
                "distance": device.get(
                    "distancia_cm"
                ),
                "status": device.get(
                    "estado"
                ),
                "last_seen": device.get(
                    "ultima_conexion"
                )
            },
            schedules=schedules,
            commands=commands,
            history=history
        )

    except Exception as error:
        return db_error(error)


# =====================================
# ALIMENTACION MANUAL
# =====================================

@bp.route("/api/feed", methods=["POST"])
@auth_required
@csrf_required
def feed():
    try:
        client = supabase()
        device = get_device()
        device_id = device["id"]

        last_seen = parse_datetime(
            device.get("ultima_conexion")
        )

        online = bool(
            last_seen and
            datetime.now(timezone.utc) - last_seen
            < timedelta(seconds=35)
        )

        level = device.get("nivel_alimento")

        if not online:
            return jsonify(
                error="ESP32 desconectado"
            ), 409

        if level is None or level <= 10:
            return jsonify(
                error="Nivel de alimento insuficiente"
            ), 409

        # RPC transaccional: la restricción única impide dos órdenes simultáneas.
        result = client.rpc("encolar_alimentacion", {"p_dispositivo_id": device_id}).execute()
        command_id = result.data
        if command_id is None:
            return jsonify(error="Ya existe una orden en curso"), 409
        return jsonify(ok=True, command_id=command_id), 201

    except Exception as error:
        return db_error(error)


# =====================================
# HORARIOS
# =====================================

@bp.route("/api/schedules", methods=["POST"])
@auth_required
@csrf_required
def add_schedule():
    data = request.get_json(silent=True) or {}

    hour = str(data.get("time", ""))
    label = str(
        data.get("label", "")
    ).strip()[:80]

    try:
        parsed = datetime.strptime(
            hour, "%H:%M"
        )

        if len(hour) != 5:
            raise ValueError()

    except ValueError:
        return jsonify(
            error="Hora inválida (HH:MM)"
        ), 400

    if not label:
        return jsonify(
            error="Ingresa un nombre"
        ), 400

    try:
        device_id = get_device_id()

        response = (
            supabase()
            .table("horarios")
            .insert({
                "dispositivo_id": device_id,
                "nombre": label,
                "hora": hour,
                "activo": True
            })
            .execute()
        )

        return jsonify(
            ok=True,
            id=response.data[0]["id"]
        ), 201

    except Exception as error:
        return db_error(error)


@bp.route(
    "/api/schedules/<int:sid>",
    methods=["PATCH", "DELETE"]
)
@auth_required
@csrf_required
def edit_schedule(sid):
    try:
        client = supabase()
        device_id = get_device_id()

        query = (
            client.table("horarios")
            .select("id")
            .eq("id", sid)
            .eq("dispositivo_id", device_id)
            .limit(1)
            .execute()
        )

        if not query.data:
            return jsonify(
                error="Horario no encontrado"
            ), 404

        if request.method == "DELETE":
            (
                client.table("horarios")
                .delete()
                .eq("id", sid)
                .eq("dispositivo_id", device_id)
                .execute()
            )

        else:
            data = request.get_json(
                silent=True
            ) or {}

            if not isinstance(
                data.get("enabled"), bool
            ):
                return jsonify(
                    error="enabled debe ser booleano"
                ), 400

            (
                client.table("horarios")
                .update({
                    "activo": data["enabled"]
                })
                .eq("id", sid)
                .eq("dispositivo_id", device_id)
                .execute()
            )

        return jsonify(ok=True)

    except Exception as error:
        return db_error(error)


# =====================================
# CONFIGURACION PARA ESP32
# =====================================

@bp.route("/api/device/config")
@device_required
def device_config():
    try:
        device_id = get_device_id()

        schedules = (
            supabase()
            .table("horarios")
            .select("id,hora")
            .eq("dispositivo_id", device_id)
            .eq("activo", True)
            .order("hora")
            .execute()
            .data
        )

        result = []

        for schedule in schedules:
            hour, minute = map(
                int,
                format_hour(
                    schedule["hora"]
                ).split(":")
            )

            result.append({
                "id": schedule["id"],
                "hour": hour,
                "minute": minute
            })

        return jsonify(
            schedules=result,
            timezone="PET5"
        )

    except Exception as error:
        return db_error(error)


# =====================================
# ORDENES PARA ESP32
# =====================================

@bp.route("/api/device/command")
@device_required
def device_command():
    try:
        client = supabase()
        device_id = get_device_id()

        result = client.rpc("tomar_orden_alimentacion", {"p_dispositivo_id": device_id}).execute()
        command_id = result.data
        if command_id is None:
            return jsonify(command=None)
        return jsonify(command={"id": command_id, "action": "feed"})

    except Exception as error:
        return db_error(error)


# =====================================
# CONFIRMACION DEL ESP32
# =====================================

@bp.route("/api/device/ack", methods=["POST"])
@device_required
def device_ack():
    data = request.get_json(silent=True) or {}

    try:
        command_id = int(
            data.get("id")
        )
    except (TypeError, ValueError):
        return jsonify(
            error="ID inválido"
        ), 400

    try:
        client = supabase()
        device_id = get_device_id()

        result = (
            client.table("ordenes")
            .select("*")
            .eq("id", command_id)
            .eq("dispositivo_id", device_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            return jsonify(
                error="Orden no encontrada"
            ), 404

        command = result.data[0]

        if command["estado"] in [
            "completado", "fallido"
        ]:
            return jsonify(ok=True)

        if command["estado"] != "procesando":
            return jsonify(
                error="Orden no procesada"
            ), 409

        success = data.get("success") is True

        status = (
            "completado"
            if success
            else "fallido"
        )

        updated = (
            client.table("ordenes")
            .update({"estado": status, "ejecutado_en": datetime.now(timezone.utc).isoformat()})
            .eq("id", command_id)
            .eq("dispositivo_id", device_id)
            .eq("estado", "procesando")
            .execute()
        )
        if updated.data:
            client.table("historial").insert({
                "dispositivo_id": device_id,
                "tipo": "manual",
                "resultado": status
            }).execute()

        return jsonify(ok=True)

    except Exception as error:
        return db_error(error)


# =====================================
# TELEMETRIA DEL ESP32
# =====================================

@bp.route(
    "/api/device/telemetry",
    methods=["POST"]
)
@device_required
def device_telemetry():
    data = request.get_json(
        silent=True
    ) or {}

    try:
        level = data.get("level")
        distance = data.get("distance")

        if level is not None:
            level = int(level)

            if not 0 <= level <= 100:
                raise ValueError()

        if distance is not None:
            distance = float(distance)

            if not 0 <= distance <= 500:
                raise ValueError()

    except (TypeError, ValueError):
        return jsonify(
            error="Telemetría inválida"
        ), 400

    try:
        device_id = get_device_id()

        (
            supabase()
            .table("dispositivos")
            .update({
                "nivel_alimento": level,
                "distancia_cm": distance,
                "estado": str(
                    data.get(
                        "status",
                        "Conectado"
                    )
                )[:32],
                "ultima_conexion": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )
            })
            .eq("id", device_id)
            .execute()
        )

        return jsonify(ok=True)

    except Exception as error:
        return db_error(error)


# =====================================
# EVENTOS AUTOMATICOS
# =====================================

@bp.route(
    "/api/device/event",
    methods=["POST"]
)
@device_required
def device_event():
    data = request.get_json(
        silent=True
    ) or {}

    source = str(
        data.get("source", "automatic")
    )[:24]

    status = str(
        data.get("status", "completed")
    )[:24]

    if source not in ("manual", "automatic") or status not in ("completed", "failed"):
        return jsonify(
            error="Tipo inválido"
        ), 400

    try:
        device_id = get_device_id()

        (
            supabase()
            .table("historial")
            .insert({
                "dispositivo_id": device_id,
                "tipo": source,
                "resultado": status
            })
            .execute()
        )

        return jsonify(ok=True), 201

    except Exception as error:
        return db_error(error)
