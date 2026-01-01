# ============================================
# Loopera WhatsApp AI Bot - Dockerfile
# ============================================
# Imagen optimizada para Railway con soporte de audio

# Base: Python 3.11 slim (menor tamano)
FROM python:3.11-slim

# Instalar ffmpeg para procesamiento de audio:
# - Convertir OGG (WhatsApp) a MP3 (Whisper)
# - Convertir WAV (TTS) a MP3 (WhatsApp)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Directorio de trabajo
WORKDIR /app

# Copiar e instalar dependencias primero (cache de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo de la aplicacion
COPY . .

# Puerto por defecto (Railway override con $PORT)
EXPOSE 8000

# Comando de inicio
# Usa python main.py para que os.getenv("PORT") funcione correctamente
# Railway no expande $PORT en CMD de Docker, pero si en python
CMD ["python", "main.py"]
