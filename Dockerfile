FROM python:3.11-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
  gcc \
  libjpeg-dev \
  zlib1g-dev \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем приложение
COPY . .

# Создаем директории для данных
RUN mkdir -p /data/db /data/media /data/avatars /data/output

# По умолчанию - интерактивный режим
CMD ["bash"]
