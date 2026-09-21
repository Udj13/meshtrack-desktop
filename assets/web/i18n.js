"use strict";

// Каталог строк интерфейса карты. MSGID — русский источник (как в Python-каталогах
// meshtrack/i18n_data/): для "ru" строки являются ключами (identity), для "en" —
// переводы. Плюрал-единицы хранятся словарями {one,few,many}/{one,other}.
const I18N = {
    ru: {
        "с": { one: "с", few: "с", many: "с" },
        "минута": { one: "минута", few: "минуты", many: "минут" },
        "час": { one: "час", few: "часа", many: "часов" },
        "день": { one: "день", few: "дня", many: "дней" }
    },
    en: {
        "с": { one: "s", other: "s" },
        "минута": { one: "minute", other: "minutes" },
        "час": { one: "hour", other: "hours" },
        "день": { one: "day", other: "days" },
        "Данные устарели (>20 мин)": "Data is stale (>20 min)",
        "Скрыть трек": "Hide track",
        "Показать трек": "Show track",
        "м/с": "m/s",
        "м": "m",
        "В": "V",
        "км/ч": "km/h",
        "Скорость: {v}": "Speed: {v}",
        "Курс: {v}°": "Course: {v}°",
        "Высота: {v} м": "Altitude: {v} m",
        "Варио: {v}": "Vario: {v}",
        "Заряд: {v} ({v2})": "Battery: {v} ({v2})",
        "Обновлено {age} назад": "Updated {age} ago"
    }
};

let LANG = "ru";

function pluralForm(n, lng) {
    if (lng === "ru") {
        const n10 = n % 10;
        const n100 = n % 100;
        if (n10 === 1 && n100 !== 11) return "one";
        if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return "few";
        return "many";
    }
    return n === 1 ? "one" : "other";
}

// Перевод строки по msgid (identity для ru).
function tt(key) {
    const d = I18N[LANG];
    if (!d) return key;
    const m = d[key];
    return typeof m === "string" ? m : key;
}

// Перевод с плюралами: key должны соответствовать словарю форм.
function plu(key, n) {
    const d = I18N[LANG];
    if (!d) return key;
    const m = d[key];
    if (typeof m === "object" && m !== null) {
        return m[pluralForm(n, LANG)] || key;
    }
    return key;
}

// Шаблон с подстановкой {name}: tt(tpl) затем замена плейсхолдеров.
function fmtTpl(tpl, params) {
    let s = tt(tpl);
    Object.keys(params).forEach(function(k) {
        s = s.replace("{" + k + "}", params[k]);
    });
    return s;
}

function applyLanguage(code) {
    if (code !== "en") code = "ru";
    LANG = code;
    document.documentElement.lang = code;
    // Пересобираем открытые попапы на новом языке.
    Object.keys(markers).forEach(function(id) {
        refreshMarkerPopup(id);
    });
}