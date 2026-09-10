"use strict";

const PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bfef45", "#808000", "#9a6324"
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

const map = L.map("map").setView([54.4, 45.4], 13);

// Фон пока серый; в Фазе 4 подключим offline MBTiles через map://
L.tileLayer("", { attribution: "" }).addTo(map);

const markers = {};
let firstPosition = true;

function updateMarker(pos) {
    const id = pos.id;
    if (!id) return;
    const color = pos.color || colorForId(id);
    const lat = parseFloat(pos.lat);
    const lon = parseFloat(pos.lon);
    const alt = pos.altitude !== undefined ? pos.altitude : "—";
    const batt = pos.batt !== undefined ? pos.batt + "%" : "—";
    const volt = pos.voltage !== undefined ? (pos.voltage / 1000).toFixed(2) + " В" : "—";
    const sos = pos.sos === 1 || pos.sos === "1";
    const ts = pos.ts || (Date.now() / 1000);

    const trend = pos.trend || "—";
    const popupHtml = `
        <b>${id}</b><br>
        GS: ${pos.gs !== undefined ? pos.gs.toFixed(1) + " км/ч" : "—"}<br>
        Высота: ${alt} м<br>
        Варио: ${pos.vario !== undefined ? pos.vario.toFixed(1) + " м/с " + trend : "—"}<br>
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
            html: `<div class="tracker-marker${sos ? " sos" : ""}" style="
                width:14px;height:14px;background:${color};">${trend}</div>`
        });
        marker = L.marker([lat, lon], { icon: icon }).addTo(map);
        marker.bindPopup(popupHtml);
        markers[id] = marker;
    } else {
        marker.setLatLng([lat, lon]);
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

    if (firstPosition) {
        map.setView([lat, lon], 13);
        firstPosition = false;
    }
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
