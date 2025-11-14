# Используем официальный Python-образ
FROM python:3.10-slim

# Отключаем буферизацию вывода (логи сразу в консоль)
ENV PYTHONUNBUFFERED=1

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в контейнер
COPY . .

# Команда по умолчанию — запуск бота
CMD ["python", "main.py"]
