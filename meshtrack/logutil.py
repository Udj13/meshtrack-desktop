"""Настройка логирования MeshTrack.

- Пишет в файл meshtrack.log в папке данных приложения.
- Предоставляет QtLogHandler для вывода последних строк в виджет окна.
"""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal


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

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("Логирование настроено: %s", log_path)
    return logger
