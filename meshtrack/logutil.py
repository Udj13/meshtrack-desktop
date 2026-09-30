"""Настройка логирования MeshTrack.

- Пишет в файл meshtrack.log в папке данных приложения с ротацией по размеру
  (2 МБ × 5 файлов, всего ~12 МБ) — лог не растёт бесконечно.
- Предоставляет QtLogHandler для вывода последних строк в виджет окна.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

# Ротация: файл растёт максимум до maxBytes, далее старые копии сдвигаются
# (meshtrack.log.1 ... meshtrack.log.N-1), старые удаляются.
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 5


class QtLogHandler(QObject, logging.Handler):
    """Handler, который испускает записи лога через Qt-сигнал.

    Подключается к QPlainTextEdit.appendPlainText() в главном окне.
    """

    logRecord = Signal(str)

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        logging.Handler.__init__(self)
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.logRecord.emit(msg)
        except Exception:
            self.handleError(record)


def setup_logging(log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Настраивает логгер `meshtrack` для приложения.

    В отличие от настройки root-логгера, не трогает глобальную конфигурацию
    pytest/CLI и не дублирует handlers при повторном вызове.

    Аргументы:
        log_path: путь к файлу лога (родительская папка создаётся).
        level:    уровень логирования.

    Возвращает логгер `meshtrack`.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("meshtrack")
    logger.setLevel(level)

    # Убираем только свои старые handlers, чтобы не мешать другим логгерам
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("Логирование настроено: %s", log_path)
    return logger
