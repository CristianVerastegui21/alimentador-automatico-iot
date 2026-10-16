
"use strict";

// =====================================
// ALIMENTADOR IOT - DASHBOARD
// =====================================

const csrf = document.querySelector(
    'meta[name="csrf-token"]'
)?.content || "";

const $ = (id) => document.getElementById(id);

let lastData = null;
let refreshing = false;
let sendingFeed = false;
let noticeTimer = null;

const PERU_TIMEZONE = "America/Lima";

// =====================================
// NOTIFICACIONES
// =====================================

function notify(message, error = false) {
    const el = $("notice");

    if (!el) return;

    clearTimeout(noticeTimer);

    el.hidden = false;
    el.textContent = message;
    el.classList.toggle("error", error);

    noticeTimer = setTimeout(() => {
        el.hidden = true;
    }, 5500);
}

// =====================================
// CONEXION CON FLASK
// =====================================

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
            ...options.headers
        }
    });

    if (response.status === 401) {
        window.location.href = "/login";
        throw new Error("Sesión expirada");
    }

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
        throw new Error(
            data.error || `Error HTTP ${response.status}`
        );
    }

    return data;
}

// =====================================
// UTILIDADES
// =====================================

function node(tag, text = "", className = "") {
    const element = document.createElement(tag);

    element.textContent = text;

    if (className) {
        element.className = className;
    }

    return element;
}

function formatDate(date) {
    if (!date) return "Sin fecha";

    const parsed = new Date(date);

    if (Number.isNaN(parsed.getTime())) {
        return "Fecha no disponible";
    }

    return parsed.toLocaleString("es-PE", {
        timeZone: PERU_TIMEZONE,
        dateStyle: "short",
        timeStyle: "short"
    });
}

function currentPeruTime() {
    return new Intl.DateTimeFormat("en-GB", {
        timeZone: PERU_TIMEZONE,
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23"
    }).format(new Date());
}

function getNextFeeding(schedules) {
    const active = schedules
        .filter(s => s.enabled)
        .map(s => String(s.hour).slice(0, 5))
        .filter(h => /^\d{2}:\d{2}$/.test(h))
        .sort();

    if (!active.length) return "--:--";

    const now = currentPeruTime();

    return active.find(hour => hour > now) || active[0];
}

// =====================================
// ESTADO DEL ESP32
// =====================================

function renderDevice(device, commands) {
    const online = Boolean(device.online);

    $("connection").textContent = online
        ? "● Dispositivo conectado"
        : "● Dispositivo desconectado";

    $("connection").className =
        "pill " + (online ? "online" : "offline");

    $("device-online").textContent = online
        ? "Conectado"
        : "Desconectado";

    $("device-status").textContent =
        device.status || "Sin datos";

    $("last-seen").textContent =
        device.last_seen
            ? formatDate(device.last_seen)
            : "Nunca";

    const level = device.level == null
        ? null
        : Number(device.level);

    const validLevel = level !== null &&
        Number.isFinite(level);

    const safeLevel = validLevel
        ? Math.max(0, Math.min(100, level))
        : 0;

    $("level").textContent = validLevel
        ? `${safeLevel}%`
        : "--%";

    $("progress-fill").style.width =
        `${safeLevel}%`;

    const progress = document.querySelector(
        ".progress[role='progressbar']"
    );

    if (progress) {
        progress.setAttribute(
            "aria-valuenow",
            String(safeLevel)
        );
    }

    $("level-message").textContent = !validLevel
        ? "Esperando telemetría"
        : safeLevel <= 10
            ? "Alimento bajo"
            : safeLevel <= 30
                ? "Nivel medio"
                : "Nivel adecuado";

    const distance = device.distance == null
        ? null
        : Number(device.distance);

    $("distance").textContent =
        distance !== null && Number.isFinite(distance)
            ? `${distance.toFixed(1)} cm`
            : "-- cm";

    const pendingCommand = commands.some(command =>
        ["pendiente", "procesando"].includes(command.status)
    );

    $("feed-button").disabled =
        sendingFeed ||
        !online ||
        !validLevel ||
        safeLevel <= 10 ||
        pendingCommand;

    const command = commands[0];

    $("command-status").textContent = command
        ? `Última orden #${command.id}: ${command.status}`
        : "Sin órdenes recientes";

    // El modo solo se mostrará si el backend lo informa.
    const mode = $("feeding-mode");

    if (mode) {
        mode.textContent =
            device.mode || "No informado";
    }
}

// =====================================
// HORARIOS
// =====================================

function renderSchedules(schedules) {
    const container = $("schedules");

    container.replaceChildren();

    if (!schedules.length) {
        container.append(
            node(
                "p",
                "No hay horarios configurados.",
                "muted"
            )
        );
    }

    schedules.forEach(schedule => {
        const row = node("div", "", "schedule-row");

        const left = node("div");

        const hour = node(
            "strong",
            String(schedule.hour).slice(0, 5)
        );

        const label = node(
            "small",
            schedule.label +
            (schedule.enabled ? "" : " · Pausado")
        );

        left.append(hour, label);

        const actions = node(
            "div",
            "",
            "row-actions"
        );

        const toggle = node(
            "button",
            schedule.enabled ? "Pausar" : "Activar",
            "tiny"
        );

        toggle.type = "button";

        toggle.addEventListener("click", () => {
            changeSchedule(
                schedule.id,
                "PATCH",
                { enabled: !schedule.enabled }
            );
        });

        const remove = node(
            "button",
            "Eliminar",
            "tiny"
        );

        remove.type = "button";

        remove.addEventListener("click", () => {
            if (confirm("¿Eliminar este horario?")) {
                changeSchedule(
                    schedule.id,
                    "DELETE"
                );
            }
        });

        actions.append(toggle, remove);
        row.append(left, actions);

        container.append(row);
    });

    $("next-feed").textContent =
        getNextFeeding(schedules);
}

// =====================================
// HISTORIAL
// =====================================

function renderHistory(history) {
    const container = $("history");

    container.replaceChildren();

    if (!history.length) {
        container.append(
            node(
                "p",
                "Aún no hay registros.",
                "muted"
            )
        );

        return;
    }

    history.forEach(item => {
        const row = node(
            "div",
            "",
            "history-row"
        );

        const left = node("div");

        const source = item.source === "manual"
            ? "Manual"
            : "Automática";

        const title = node(
            "strong",
            `${source} · ${item.status}`
        );

        const date = node(
            "small",
            `${formatDate(item.time)} · ${
                item.description || "Sin detalle"
            }`
        );

        left.append(title, date);
        row.append(left);

        container.append(row);
    });
}

// =====================================
// ACTUALIZAR DASHBOARD
// =====================================

function render(data) {
    lastData = data;

    renderDevice(
        data.device || {},
        data.commands || []
    );

    renderSchedules(data.schedules || []);

    renderHistory(data.history || []);
}

async function refresh() {
    if (refreshing) return;

    refreshing = true;

    try {
        const data = await api("/api/status");

        render(data);

    } catch (error) {
        console.error(
            "Error actualizando dashboard:",
            error
        );

        $("connection").textContent =
            "● Sin comunicación con el servidor";

        $("connection").className =
            "pill offline";

        $("feed-button").disabled = true;

    } finally {
        refreshing = false;
    }
}

// =====================================
// CREAR / MODIFICAR HORARIOS
// =====================================

async function changeSchedule(id, method, data) {
    try {
        await api(`/api/schedules/${id}`, {
            method,
            body: data
                ? JSON.stringify(data)
                : undefined
        });

        notify("Horario actualizado correctamente");

        await refresh();

    } catch (error) {
        notify(error.message, true);
    }
}

$("schedule-form").addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        const form = event.currentTarget;
        const button = $("add-schedule") ||
            form.querySelector(
                'button[type="submit"]'
            );

        const formData = new FormData(form);

        const time = formData.get("time");
        const label = String(
            formData.get("label") || ""
        ).trim();

        if (!time || !label) {
            notify(
                "Completa la hora y el nombre",
                true
            );
            return;
        }

        button.disabled = true;

        try {
            await api("/api/schedules", {
                method: "POST",
                body: JSON.stringify({
                    time,
                    label
                })
            });

            notify("Horario guardado correctamente");

            form.reset();

            await refresh();

        } catch (error) {
            notify(error.message, true);

        } finally {
            button.disabled = false;
        }
    }
);

// =====================================
// ALIMENTACION MANUAL
// =====================================

const feedDialog = $("feed-dialog");
const feedButton = $("feed-button");

async function sendFeedCommand() {
    if (sendingFeed || feedButton.disabled) return;

    sendingFeed = true;
    feedButton.disabled = true;

    $("command-status").textContent =
        "Enviando orden...";

    try {
        await api("/api/feed", {
            method: "POST",
            body: JSON.stringify({})
        });

        notify("Orden enviada al ESP32");

        await refresh();

    } catch (error) {
        notify(error.message, true);

    } finally {
        sendingFeed = false;

        // Actualiza el estado real del botón.
        await refresh();
    }
}

feedButton.addEventListener("click", () => {
    if (feedButton.disabled) return;

    if (feedDialog?.showModal) {
        feedDialog.showModal();
    } else if (confirm(
        "¿Deseas dispensar alimento ahora?"
    )) {
        sendFeedCommand();
    }
});

$("cancel-feed")?.addEventListener(
    "click",
    () => feedDialog.close()
);

$("confirm-feed")?.addEventListener(
    "click",
    () => {
        feedDialog.close();
        sendFeedCommand();
    }
);

// =====================================
// INICIALIZACION
// =====================================

refresh();

// Actualización automática cada 5 segundos.
setInterval(refresh, 5000);
