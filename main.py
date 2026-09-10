import serial
import requests
import re
from datetime import datetime
import time
import os
import sys
from collections import OrderedDict
import serial.tools.list_ports

class TrackerMonitor:
    def __init__(self):
        self.trackers = OrderedDict()
        self.last_update = datetime.now()
        self.queue_size = 0
        self.max_queue_size = 100
        self.send_to_server = True  # По умолчанию отправляем на сервер

    def update_queue_size(self, size):
        """Обновляет размер очереди сообщений"""
        self.queue_size = size
        self.last_update = datetime.now()

    def update_tracker(self, tracker_id, data, status):
        """Обновляет данные трекера"""
        self.trackers[tracker_id] = {
            'lat': data.get('lat', 'N/A'),
            'lon': data.get('lon', 'N/A'),
            'altitude': data.get('altitude', 'N/A'),
            'timestamp': data.get('timestamp', 'N/A'),
            'voltage': data.get('voltage', 'N/A'),
            'batt': data.get('batt', 'N/A'),
            'status': status,
            'last_update': datetime.now()
        }
        self.last_update = datetime.now()

    def display(self):

        # Ширина дисплея
        display_width = 86

        """Отображает интерфейс с данными трекеров и полосой загрузки"""
        # Очищаем экран
        os.system('cls' if os.name == 'nt' else 'clear')

        # Выводим заголовок с полосой загрузки очереди
        print("🚀 Tracker Monitor - Live Data")
        print("=" * display_width)

        # Отображаем информацию о конфигурации
        server_status = "✅ Отправка на сервер: ВКЛ" if self.send_to_server else "❌ Отправка на сервер: ВЫКЛ"
        print(server_status)

        # Отображаем полосу загрузки очереди
        queue_percent = (self.queue_size / self.max_queue_size) * 100
        bar_length = 30
        filled_length = int(bar_length * self.queue_size // self.max_queue_size)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)

        print(f"📊 Очередь сообщений: [{bar}] {self.queue_size}/{self.max_queue_size} ({queue_percent:.1f}%)")
        print("-" * display_width)

        # Выводим таблицу с данными трекеров
        print(f"{'ID':<10} {'Latitude':<12} {'Longitude':<12} {'Altitude':<8} {'Time':<19} {'Voltage':<8} {'Batt':<4} {'Status':<6}")
        print("-" * display_width)

        # Выводим данные всех трекеров
        for tracker_id, data in self.trackers.items():
            # Форматируем время для отображения
            if data['timestamp'] != 'N/A':
                time_str = data['timestamp'].replace('T', ' ').replace('Z', '')
            else:
                time_str = 'N/A'

            print(f"{tracker_id:<10} {data['lat']:<12} {data['lon']:<12} {data['altitude']:<8} {time_str:<19} {data['voltage']:<8} {data['batt']:<4} {data['status']:<6}")

        # Выводим время последнего обновления
        print("-" * display_width)
        print(f"Last update: {self.last_update.strftime('%Y-%m-%d %H:%M:%S')}")
        print("Press Ctrl+C to exit")
        print("=" * display_width)
        print()


def parse_data(data_block):
    """Парсит блок данных и извлекает нужные параметры"""
    params = {}

    # Используем регулярные выражения для извлечения данных
    patterns = {
        'id': r'Device ID:\s+(\d+)',
        'lat': r'Latitude:\s+([\d.]+)',
        'lon': r'Longitude:\s+([\d.]+)',
        'altitude': r'Altitude:\s+(\d+)',
        'datetime': r'Date/Time:\s+([\d-]+\s+[\d:]+)',
        'sos': r'SOS:\s+(\d+)',
        'voltage': r'Battery Voltage:\s+(\d+)',
        'batt': r'Battery Level:\s+(\d+)%'
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, data_block)
        if match:
            params[key] = match.group(1)

    # Преобразуем дату/время в формат ISO
    if 'datetime' in params:
        try:
            dt = datetime.strptime(params['datetime'], '%Y-%m-%d %H:%M:%S')
            params['timestamp'] = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            del params['datetime']
        except ValueError:
            params['timestamp'] = 'N/A'

    # Формируем полный ID устройства
    if 'id' in params:
        params['id'] = f"boon{params['id']}"

    return params

def send_to_traccar(params):
    """Отправляет данные на сервер Traccar"""
    url = "http://free-gps.ru:5055"

    # Формируем параметры запроса
    payload = {
        'id': params.get('id'),
        'lat': params.get('lat'),
        'lon': params.get('lon'),
        'altitude': params.get('altitude'),
        'timestamp': params.get('timestamp'),
        'sos': params.get('sos', '0'),
        'voltage': params.get('voltage'),
        'batt': params.get('batt'),
        'ttl': '3'
    }

    # Убираем None значения
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            return True, "✅"
        else:
            return False, f"❌{response.status_code}"
    except Exception as e:
        return False, "❌NET"

def parse_queue_size(line):
    """Извлекает размер очереди из строки"""
    match = re.search(r'Queue size:\s+(\d+)', line)
    if match:
        return int(match.group(1))
    return None

def get_available_ports():
    """Возвращает список доступных serial портов"""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

def select_serial_port():
    """Позволяет пользователю выбрать serial порт из списка доступных"""
    ports = get_available_ports()

    if not ports:
        print("❌ Не найдено доступных serial портов!")
        return None

    print("📋 Доступные serial порты:")
    for i, port in enumerate(ports, 1):
        print(f"{i}. {port}")

    while True:
        try:
            choice = int(input("\nВыберите порт (введите номер): "))
            if 1 <= choice <= len(ports):
                return ports[choice - 1]
            else:
                print("❌ Неверный выбор. Попробуйте снова.")
        except ValueError:
            print("❌ Пожалуйста, введите число.")

def ask_send_to_server():
    """Спрашивает пользователя, нужно ли отправлять данные на сервер"""
    while True:
        response = input("\nОтправлять данные на сервер? (y/n): ").lower()
        if response in ['y', 'yes', 'д', 'да']:
            return True
        elif response in ['n', 'no', 'н', 'нет']:
            return False
        else:
            print("❌ Пожалуйста, введите 'y' или 'n'.")

def ask_show_log():
    """Спрашивает пользователя, нужно ли показывать лог"""
    while True:
        response = input("\nПоказывать лог? (y/n): ").lower()
        if response in ['y', 'yes', 'д', 'да']:
            return True
        elif response in ['n', 'no', 'н', 'нет']:
            return False
        else:
            print("❌ Пожалуйста, введите 'y' или 'n'.")


def main():
    # Конфигурация при запуске
    print("🛠️  Конфигуратор Tracker Monitor")
    print("=" * 40)

    # Выбор serial порта
    serial_port = select_serial_port()
    if not serial_port:
        return

    # Настройка отправки на сервер
    send_to_server = ask_send_to_server()

    # Настройка показа лога
    show_log = ask_show_log()

    # Настройка скорости передачи
    baud_rate = 115200

    # Инициализируем монитор
    monitor = TrackerMonitor()
    monitor.send_to_server = send_to_server

    try:
        # Подключаемся к serial порту
        ser = serial.Serial(serial_port, baud_rate, timeout=1)
        print(f"\n📡 Подключено к {serial_port} с Baud rate {baud_rate}")
        print("Загрузка данных...")
        time.sleep(2)

        buffer = ""
        in_data_block = False

        # Первоначальное отображение
        monitor.display()

        log_lines = 0;

        while True:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()

                    if show_log:
                        print(line)
                        log_lines += 1
                        if log_lines > 20:
                            log_lines = 0
                            monitor.display()
                except UnicodeDecodeError:
                    continue

                # Проверяем размер очереди
                queue_size = parse_queue_size(line)
                if queue_size is not None:
                    monitor.update_queue_size(queue_size)
                    monitor.display()

                # Пропускаем пустые строки и AT команды
                if not line or line.startswith('AT') or line.startswith('RAW LINE'):
                    continue

                # Ищем начало блока данных
                if "Radio Received packet!" in line:
                    in_data_block = True
                    buffer = ""
                    continue

                # Если мы внутри блока данных, собираем строки
                if in_data_block:
                    buffer += line + "\n"

                    # Проверяем, достигли ли мы конца блока данных
                    if "Postfix: OK" in line or "Received valid LoRa data packet!" in line:
                        in_data_block = False

                        # Парсим данные
                        params = parse_data(buffer)
                        if params and 'id' in params:
                            # Отправляем данные на сервер, если включено
                            if monitor.send_to_server:
                                success, status = send_to_traccar(params)
                            else:
                                status = "⏸️"  # Символ паузы, если отправка отключена

                            # Обновляем монитор
                            monitor.update_tracker(params['id'], params, status)

                            # Обновляем дисплей
                            monitor.display()

                        buffer = ""

            # Небольшая задержка для снижения нагрузки на CPU
            time.sleep(0.1)

    except serial.SerialException as e:
        print(f"❌ Ошибка подключения к serial порту: {e}")
    except KeyboardInterrupt:
        print("\n👋 Скрипт остановлен пользователем")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("🔌 Serial порт закрыт")

if __name__ == "__main__":
    main()
