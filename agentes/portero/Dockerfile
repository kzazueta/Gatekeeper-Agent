FROM python:3.11-slim

# Instalar dependencias del sistema para psycopg2
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requisitos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código del agente
COPY agente_portero.py .
COPY interfaz_prueba.py .

# Variables de entorno por defecto
ENV MQTT_HOST=broker-mqtt
ENV MQTT_PORT=1883
ENV DB_HOST=bd-portero
ENV DB_PORT=5432
ENV DB_NAME=portero_local
ENV DB_USER=portero
ENV DB_PASSWORD=portero123

# Ejecutar agente
CMD ["python", "-u", "agente_portero.py"]
