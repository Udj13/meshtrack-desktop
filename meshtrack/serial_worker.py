"""Serial-ридер в отдельном QThread.

Читает поток построчно и парсит JSON-строки пакетов (по одной на пакет),
испуская сигналы для основного потока.
"""
import serial
from PySide6.QtCore import QThread, Signal

from .parser import (
    is_valid_position,
    parse_packet,
    parse_queue_size,
)


class SerialWorker(QThread):
    """Поток чтения из serial-порта или file-URL.

    Сигналы:
        position(dict): валидная parsed-позиция.
        raw_line(str):   сырая строка из порта (для отладки/лога).
        error(str):     ошибка открытия/чтения порта.
        queue_size(int): размер очереди приёмника (Queue size: N).
    """

    position = Signal(dict)
    raw_line = Signal(str)
    error = Signal(str)
    queue_size = Signal(int)

    def __init__(self, port: str, baud: int = 115200, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._running = False
        self._ser = None

    def run(self):
        self._running = True
        is_file = self.port.startswith("file://")
        try:
            if is_file:
                path = self.port[len("file://") :]
                self._ser = open(path, "r", encoding="utf-8", errors="replace")
            else:
                self._ser = serial.Serial(
                    self.port, self.baud, timeout=1.0, write_timeout=0
                )
        except Exception as exc:  # pragma: no cover - hardware error
            self.error.emit(f"Cannot open {self.port}: {exc}")
            self._running = False
            return

        while self._running:
            try:
                data = self._ser.readline()
            except serial.SerialException as exc:
                self.error.emit(f"Serial read error: {exc}")
                break
            except OSError as exc:
                self.error.emit(f"Read error: {exc}")
                break

            if data == b"" or data == "":
                # Файл закончился; serial таймаут → ждём новых данных
                if is_file:
                    break
                continue

            if isinstance(data, bytes):
                line = data.decode("utf-8", errors="replace").rstrip("\r\n")
            else:
                line = data.rstrip("\r\n")

            if not line:
                continue

            self.raw_line.emit(line)

            qs = parse_queue_size(line)
            if qs is not None:
                self.queue_size.emit(qs)

            parsed = parse_packet(line)
            if parsed is not None and is_valid_position(parsed):
                self.position.emit(parsed)

        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._running = False

    def stop(self):
        """Безопасно останавливает поток."""
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self.wait(2000)
