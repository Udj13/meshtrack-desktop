"use strict";

const PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bfef45", "#3cb44b",
    "#808000", "#9a6324"
];

function colorForId(id) {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
        hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
    }
    return PALETTE[hash % PALETTE.length];
}

function formatAge(tsSec) {
    const dt = Math.max(0, Math.floor((Date.now() / 1000) - tsSec));
    if (dt < 60) return dt + " с";
    return Math.floor(dt / 60) + " мин";
}

const map = L.map("map", { attributionControl: false }).setView([54.4, 45.4], 13);

// Фон пока серый; в Фазе 4 подключим offline MBTiles через map://
L.tileLayer("", { attribution: "" }).addTo(map);

const markers = {};
const arrows = {};
let firstPosition = true;

function makeMarkerHtml(color, trend, sos) {
    return `<div class="tracker-marker${sos ? " sos" : ""}" style="
        width:14px;height:14px;background:${color};">${trend}</div>`;
}

function makeArrowHtml(color, lengthPx, courseDeg) {
    // courseDeg: 0° = север. В CSS 0° = восток (3 часа), поэтому сдвигаем на -90°.
    const rotate = (courseDeg - 90).toFixed(1);
    return `<div class="course-arrow" style="
        width:${lengthPx.toFixed(0)}px;background:${color};
        transform:rotate(${rotate}deg);"></div>`;
}

function updateMarker(pos) {
    const id = pos.id;
    if (!id) return;
    const color = pos.color || colorForId(id);
    const lat = parseFloat(pos.lat);
    const lon = parseFloat(pos.lon);
    const alt = pos.altitude !== undefined && pos.altitude !== null ? pos.altitude : "—";
    const batt = pos.batt !== undefined && pos.batt !== null ? pos.batt + "%" : "—";
    const volt = pos.voltage !== undefined && pos.voltage !== null ? (pos.voltage / 1000).toFixed(2) + " В" : "—";
    const sos = pos.sos === 1 || pos.sos === "1";
    const ts = pos.ts || (Date.now() / 1000);

    const trend = pos.trend || "—";
    const gs = pos.gs_kmh !== undefined && pos.gs_kmh !== null ? pos.gs_kmh.toFixed(1) : null;
    const course = pos.course_deg !== undefined && pos.course_deg !== null ? pos.course_deg.toFixed(0) : null;
    const vario = pos.vario_ms !== undefined && pos.vario_ms !== null ? pos.vario_ms.toFixed(1) : null;

    const popupHtml = `
        <b>${id}</b><br>
        GS: ${gs !== null ? gs + " км/ч" : "—"}<br>
        Курс: ${course !== null ? course + "°" : "—"}<br>
        Высота: ${alt} м<br>
        Варио: ${vario !== null ? vario + " м/с " + trend : "—"}<br>
        Заряд: ${batt} (${volt})<br>
        Обновлено ${formatAge(ts)} назад
        ${sos ? "<br><span style='color:red;font-weight:bold;'>SOS</span>" : ""}
    `;

    let marker = markers[id];
    if (!marker) {
        const icon = L.divIcon({
            className: "",
            iconSize: [14, 14],
            iconAnchor: [7, 7],
            html: makeMarkerHtml(color, trend, sos)
        });
        marker = L.marker([lat, lon], { icon: icon, zIndexOffset: 1000 }).addTo(map);
        marker.bindPopup(popupHtml);
        markers[id] = marker;
    } else {
        marker.setLatLng([lat, lon]);
        marker.setZIndexOffset(1000);
        const el = marker.getElement();
        if (el) {
            const inner = el.querySelector(".tracker-marker");
            if (inner) {
                inner.style.background = color;
                inner.textContent = trend;
                inner.classList.toggle("sos", sos);
            }
        }
        marker.setPopupContent(popupHtml);
    }

    // Стрелка курса: длина ∝ GS (1 пиксель на км/ч), максимум 80 px
    let arrow = arrows[id];
    const arrowLen = gs !== null ? Math.min(parseFloat(gs), 80) : 0;
    if (arrowLen > 0 && course !== null) {
        const arrowIcon = L.divIcon({
            className: "",
            iconSize: [arrowLen, 4],
            iconAnchor: [0, 2],
            html: makeArrowHtml(color, arrowLen, parseFloat(course))
        });
        if (!arrow) {
            arrow = L.marker([lat, lon], { icon: arrowIcon, zIndexOffset: 500, interactive: false }).addTo(map);
            arrows[id] = arrow;
        } else {
            arrow.setLatLng([lat, lon]);
            arrow.setIcon(arrowIcon);
        }
    } else if (arrow) {
        map.removeLayer(arrow);
        delete arrows[id];
    }

    if (firstPosition) {
        map.setView([lat, lon], 13);
        firstPosition = false;
    }
}

function centerTracker(id) {
    const marker = markers[id];
    if (marker) {
        map.panTo(marker.getLatLng());
        marker.openPopup();
    }
}

function toggleTrack(id) {
    // Заглушка для Фазы 2; полноценный трек появится в Фазе 3
    console.log("toggleTrack requested for", id);
}

function onPosition(pos) {
    try {
        updateMarker(pos);
    } catch (e) {
        console.error("updateMarker error:", e);
    }
}

if (typeof qt !== "undefined") {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        const bridge = channel.objects.bridge;
        if (bridge) {
            bridge.positionReceived.connect(onPosition);
            console.log("bridge connected");
        } else {
            console.error("bridge not found in QWebChannel");
        }
    });
} else {
    console.warn("qt object not available — running outside QtWebEngine");
}
