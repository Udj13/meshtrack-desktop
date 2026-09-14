"""Опциональная отправка позиций на Traccar (free-gps.ru).

Модуль не зависит от Qt: очередь (`collections.deque`) обслуживается фоновым
потоком `threading`. При `enable=False` метод `enqueue()` — no-op, ни одного
сетевого запроса не выполняется (PROJECT.md §11).

Поведение при ошибках: payload возвращается в очередь и повторяется; после
`max_failed` подряд идущих ошибок отправка ставится на паузу `pause_s` секунд,
после чего очередь продолжает разбираться.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

import requests

TRACCAR_URL = "http://free-gps.ru:5055"
MAX_FAILED = 5
PAUSE_S = 300.0
POST_TIMEOUT = 10.0
RETRY_DELAY_S = 1.0


def build_payload(pos: dict) -> dict:
    """Формирует payload как в легаси `main.py` (timestamp — ISO, ttl=3).

    Пустые значения отбрасываются; `sos` по умолчанию '0'.
    """
    timestamp = pos.get("timestamp")
    if not timestamp or timestamp == "N/A":
        ts = pos.get("ts")
        if ts is not None:
            try:
                timestamp = datetime.fromtimestamp(
                    float(ts), tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError, OSError):
                timestamp = None
        else:
            timestamp = None

    sos = pos.get("sos")
    payload = {
        "id": pos.get("id"),
        "lat": pos.get("lat"),
        "lon": pos.get("lon"),
        "altitude": pos.get("altitude"),
        "timestamp": timestamp,
        "sos": "0" if sos is None else sos,
        "voltage": pos.get("voltage"),
        "batt": pos.get("batt"),
        "ttl": "3",
    }
    return {k: v for k, v in payload.items() if v is not None}


class TraccarPublisher:
    """Очередь отправки на Traccar с ретраями в фоновом потоке.

    Аргументы:
        enable: включена ли отправка (по умолчанию False).
        url: endpoint (в легаси фиксирован free-gps.ru:5055).
        post: инъекция функции отправки (для тестов); по умолчанию
            `requests.post`.
        max_failed: число подряд ошибок до длинной паузы.
        pause_s: длительность паузы после `max_failed` (сек).
        retry_delay_s: пауза между обычными попытками (сек).
        logger: логгер; по умолчанию `logging.getLogger(__name__)`.
    """

    def __init__(
        self,
        enable: bool = False,
        url: str = TRACCAR_URL,
        post: Callable[..., object] | None = None,
        timeout: float = POST_TIMEOUT,
        max_failed: int = MAX_FAILED,
        pause_s: float = PAUSE_S,
        retry_delay_s: float = RETRY_DELAY_S,
        logger: logging.Logger | None = None,
    ):
        self.enable = bool(enable)
        self._url = url
        self._post = post or requests.post
        self._timeout = timeout
        self._max_failed = max_failed
        self._pause_s = pause_s
        self._retry_delay_s = retry_delay_s
        self._log = logger or logging.getLogger(__name__)

        self._queue: deque[dict] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._failed = 0
        self._paused_until = 0.0
        self._stopping = False
        self._inflight = False
        self._thread: threading.Thread | None = None

    # --- публичный API -------------------------------------------------

    @property
    def pending(self) -> int:
        """Сколько payload'ов ждёт отправки."""
        with self._lock:
            return len(self._queue)

    @property
    def failed(self) -> int:
        """Счётчик подряд идущих ошибок."""
        return self._failed

    def start(self) -> None:
        """Запускает фоновый поток (идемпотентно)."""
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="traccar-publisher", daemon=True
            )
            self._thread.start()

    def enqueue(self, pos: dict) -> None:
        """Ставит позицию в очередь; при `enable=False` — no-op."""
        if not self.enable:
            return
        payload = build_payload(pos)
        if not payload.get("id") or payload.get("lat") is None or payload.get("lon") is None:
            return
        self.start()
        with self._wake:
            self._queue.append(payload)
            self._wake.notify_all()

    def flush(self, timeout: float = 5.0) -> bool:
        """Блокируется, пока очередь не опустеет (для тестов/закрытия)."""
        self.start()
        deadline = time.monotonic() + timeout
        with self._wake:
            while (self._queue or self._inflight) and not self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._wake.wait(min(remaining, 0.05))
            return not self._queue and not self._inflight

    def stop(self, timeout: float = 2.0) -> None:
        """Останавливает фоновый поток."""
        with self._wake:
            self._stopping = True
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)

    # --- внутреннее -----------------------------------------------------

    def _send(self, payload: dict) -> tuple[bool, str]:
        try:
            response = self._post(self._url, data=payload, timeout=self._timeout)
            code = getattr(response, "status_code", 0)
            if code == 200:
                return True, "ok"
            return False, f"HTTP {code}"
        except Exception as exc:  # сетевые ошибки не должны ронять поток
            return False, type(exc).__name__

    def _run(self) -> None:
        while True:
            with self._wake:
                while True:
                    if self._stopping:
                        return
                    if not self.enable:
                        self._queue.clear()
                    now = time.monotonic()
                    if self._queue and self.enable and now >= self._paused_until:
                        payload = self._queue.popleft()
                        self._inflight = True
                        break
                    wait_s = 1.0
                    if self._queue and now < self._paused_until:
                        wait_s = min(1.0, self._paused_until - now)
                    self._wake.wait(wait_s)

            ok, info = self._send(payload)

            with self._wake:
                self._inflight = False
                if ok:
                    self._failed = 0
                    self._log.debug("Traccar: отправлено %s", payload.get("id"))
                else:
                    self._failed += 1
                    self._queue.appendleft(payload)
                    if self._failed >= self._max_failed:
                        self._paused_until = time.monotonic() + self._pause_s
                        self._log.warning(
                            "Traccar недоступен (%s); пауза %.0f с, в очереди %d",
                            info,
                            self._pause_s,
                            len(self._queue),
                        )
                        self._failed = 0
                    else:
                        self._paused_until = time.monotonic() + self._retry_delay_s
                        self._log.warning(
                            "Traccar: ошибка отправки (%s), повтор", info
                        )
                self._wake.notify_all()
