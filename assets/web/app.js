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

// --- Цветовые режимы трека ---
function colorForAltitude(alt) {
    // синий (0 м) -> красный (4000 м)
    const a = Math.max(0, Math.min(4000, alt || 0)) / 4000;
    const r = Math.round(255 * a);
    const b = Math.round(255 * (1 - a));
    return `rgb(${r}, 0, ${b})`;
}

function colorForVario(vario) {
    // зелёный (+5 м/с) → серый (0) → красный (−5 м/с)
    const v = Math.max(-5, Math.min(5, vario || 0));
    if (v >= 0) {
        const k = v / 5; // 0..1
        const r = Math.round(128 * (1 - k));
        const g = Math.round(128 + 127 * k);
        return `rgb(${r}, ${g}, ${r})`;
    } else {
        const k = -v / 5; // 0..1
        const g = Math.round(128 * (1 - k));
        const b = Math.round(128 * (1 - k));
        return `rgb(255, ${g}, ${b})`;
    }
}

const map = L.map("map", { attributionControl: false }).setView([54.4, 45.4], 13);
L.control.attribution({ prefix: false }).addTo(map);

let offlineLayer = null;
let currentMapMinZoom = 2;
let currentMapMaxZoom = 18;

function applyMapZoomLimits(minZoom, maxZoom) {
    currentMapMinZoom = minZoom;
    currentMapMaxZoom = maxZoom;
    map.setMinZoom(minZoom);
    map.setMaxZoom(maxZoom);
    console.log("Map zoom limits:", minZoom, "-", maxZoom);
}

function setOfflineMapLayer(mapId, minZoom, maxZoom) {
    if (!mapId) {
        clearOfflineMapLayer();
        return;
    }
    const url = "map://" + mapId + "/{z}/{x}/{y}.png";
    console.log("Switching offline map layer to:", url, "zoom", minZoom, "-", maxZoom);
    if (offlineLayer) {
        map.removeLayer(offlineLayer);
    }
    offlineLayer = L.tileLayer(url, {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL), SRTM | © OpenTopoMap (CC-BY-SA)',
        minZoom: minZoom,
        maxZoom: maxZoom,
        tileSize: 256
    }).addTo(map);
    applyMapZoomLimits(minZoom, maxZoom);
}

function clearOfflineMapLayer() {
    console.log("Clearing offline map layer");
    if (offlineLayer) {
        map.removeLayer(offlineLayer);
        offlineLayer = null;
    }
    applyMapZoomLimits(2, 18);
}

function loadMapWithZoom(mapId) {
    if (!bridge) return;
    if (!mapId) {
        clearOfflineMapLayer();
        return;
    }
    bridge.getMinZoom(function(minZoom) {
        bridge.getMaxZoom(function(maxZoom) {
            minZoom = parseInt(minZoom) || 2;
            maxZoom = parseInt(maxZoom) || 18;
            setOfflineMapLayer(mapId, minZoom, maxZoom);
        });
    });
}

// Фон пока серый; слой установит bridge при подключении

const markers = {};
const arrows = {};
const trackLayers = {};
const visibleTracks = new Set();
const lastTrackReload = {};
let firstPosition = true;

// Как часто (мс) обновлять трек видимого трекера при поступлении новых точек.
const TRACK_RELOAD_INTERVAL_MS = 5000;

let trackFilter = { from: 0, to: 0 };
let trackColorMode = "palette";

function makeMarkerHtml(color, trend, sos, stale) {
    const extra = (sos ? " sos" : "") + (stale ? " stale" : "");
    return `<div class="tracker-marker${extra}" style="
        width:14px;height:14px;background:${color};">${trend}</div>`;
}

function makeArrowHtml(color, lengthPx, courseDeg, stale) {
    // courseDeg: 0° = север. В CSS 0° = восток (3 часа), поэтому сдвигаем на -90°.
    const rotate = (courseDeg - 90).toFixed(1);
    const extra = stale ? " stale" : "";
    return `<div class="course-arrow${extra}" style="
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
    const stale = Boolean(pos.stale);
    const ts = pos.ts || (Date.now() / 1000);

    const trend = pos.trend || "—";
    const gs = pos.gs_kmh !== undefined && pos.gs_kmh !== null ? pos.gs_kmh.toFixed(1) : null;
    const course = pos.course_deg !== undefined && pos.course_deg !== null ? pos.course_deg.toFixed(0) : null;
    const vario = pos.vario_ms !== undefined && pos.vario_ms !== null ? pos.vario_ms.toFixed(1) : null;

    const staleHtml = stale
        ? "<br><span style='color:gray;font-weight:bold;'>Данные устарели (>20 мин)</span>"
        : "";
    const trackLink = `<a href="#" onclick="event.preventDefault(); toggleTrack('${id}'); return false;">${
        visibleTracks.has(id) ? "Скрыть трек" : "Показать трек"
    }</a>`;
    const popupHtml = `
        <b>${pos.name || id}</b>${pos.name ? ` <span style="color:gray;font-size:11px;">(${id})</span>` : ""}<br>
        Скорость: ${gs !== null ? gs + " км/ч" : "—"}<br>
        Курс: ${course !== null ? course + "°" : "—"}<br>
        Высота: ${alt} м<br>
        Варио: ${vario !== null ? vario + " м/с " + trend : "—"}<br>
        Заряд: ${batt} (${volt})<br>
        Обновлено ${formatAge(ts)} назад
        ${sos ? "<br><span style='color:red;font-weight:bold;'>SOS</span>" : ""}
        ${staleHtml}
        <br>${trackLink}
    `;

    let marker = markers[id];
    if (!marker) {
        const icon = L.divIcon({
            className: "",
            iconSize: [14, 14],
            iconAnchor: [7, 7],
            html: makeMarkerHtml(color, trend, sos, stale)
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
                inner.classList.toggle("stale", stale);
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
            html: makeArrowHtml(color, arrowLen, parseFloat(course), stale)
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

// --- Треки ---
function removeTrack(id) {
    const layer = trackLayers[id];
    if (layer) {
        map.removeLayer(layer);
        delete trackLayers[id];
    }
}

function drawTrack(id, points, mode) {
    removeTrack(id);
    if (!points || points.length < 2) return;

    const color = colorForId(id);

    if (mode === "palette") {
        const latlngs = points.map(p => [p.lat, p.lon]);
        trackLayers[id] = L.polyline(latlngs, {
            color: color,
            weight: 3,
            opacity: 0.85
        }).addTo(map);
        return;
    }

    const group = L.layerGroup().addTo(map);
    for (let i = 1; i < points.length; i++) {
        const p1 = points[i - 1];
        const p2 = points[i];
        let segColor;
        if (mode === "altitude") {
            segColor = colorForAltitude(((p1.alt || 0) + (p2.alt || 0)) / 2);
        } else { // vario
            const dt = p2.ts - p1.ts;
            const vario = dt > 0 ? ((p2.alt || 0) - (p1.alt || 0)) / dt : 0;
            segColor = colorForVario(vario);
        }
        L.polyline([[p1.lat, p1.lon], [p2.lat, p2.lon]], {
            color: segColor,
            weight: 3,
            opacity: 0.85
        }).addTo(group);
    }
    trackLayers[id] = group;
}

function loadTrack(id) {
    if (!bridge) return;
    bridge.getTrack(id, trackFilter.from, trackFilter.to, function(jsonStr) {
        try {
            const data = JSON.parse(jsonStr);
            drawTrack(id, data.points, trackColorMode);
        } catch (e) {
            console.error("loadTrack parse error:", e);
        }
    });
}

function showTrack(id) {
    visibleTracks.add(id);
    loadTrack(id);
}

function hideTrack(id) {
    visibleTracks.delete(id);
    removeTrack(id);
}

function toggleTrack(id) {
    if (visibleTracks.has(id)) {
        hideTrack(id);
    } else {
        showTrack(id);
    }
}

function setTrackFilter(fromTs, toTs) {
    trackFilter.from = fromTs;
    trackFilter.to = toTs;
    refreshVisibleTracks();
}

function setTrackColorMode(mode) {
    trackColorMode = mode;
    refreshVisibleTracks();
}

function refreshVisibleTracks() {
    visibleTracks.forEach(function(id) {
        loadTrack(id);
    });
}

function clearAllTracks() {
    visibleTracks.forEach(removeTrack);
    visibleTracks.clear();
}

function onHistoryCleared() {
    clearAllTracks();
}

function onPosition(pos) {
    try {
        updateMarker(pos);
        // Видимые треки догружаем по мере поступления новых точек: иначе трек,
        // включённый до появления истории, так и остался бы пустым.
        if (pos.id && visibleTracks.has(pos.id)) {
            const nowMs = Date.now();
            const last = lastTrackReload[pos.id] || 0;
            if (nowMs - last >= TRACK_RELOAD_INTERVAL_MS) {
                lastTrackReload[pos.id] = nowMs;
                loadTrack(pos.id);
            }
        }
    } catch (e) {
        console.error("updateMarker error:", e);
    }
}

let bridge = null;

if (typeof qt !== "undefined") {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.bridge;
        if (bridge) {
            bridge.positionReceived.connect(onPosition);
            if (bridge.historyCleared) {
                bridge.historyCleared.connect(onHistoryCleared);
            }
            if (bridge.getColorMode) {
                bridge.getColorMode(function(mode) {
                    if (mode) trackColorMode = mode;
                });
            }
            if (bridge.getActiveMapId) {
                bridge.getActiveMapId(function(mapId) {
                    console.log("Initial active map id:", mapId);
                    loadMapWithZoom(mapId);
                });
            } else {
                console.warn("bridge.getActiveMapId not available");
            }
            if (bridge.activeMapChanged) {
                bridge.activeMapChanged.connect(function(mapId) {
                    console.log("Active map changed:", mapId);
                    loadMapWithZoom(mapId);
                });
            }
            console.log("bridge connected");
        } else {
            console.error("bridge not found in QWebChannel");
        }
    });
} else {
    console.warn("qt object not available — running outside QtWebEngine");
}
