# Loopera WhatsApp AI Bot

Bot de WhatsApp con IA que procesa texto, imagenes y notas de voz. Responde con voz cuando recibe notas de voz.

## Features

| Feature | Tecnologia | Status |
|---------|------------|--------|
| Texto -> Texto | Llama 3.3 70B | OK |
| Voz -> Voz (Ingles) | Whisper + Llama + PlayAI TTS | OK |
| Voz -> Voz (Espanol) | Whisper + Llama + Google TTS | OK |
| Imagenes -> Texto | Llama 4 Scout Vision | OK |
| Memoria conversacional | Redis (24h) | OK |
| Bilingue | Espanol + Ingles | OK |

## Arquitectura

```
Usuario -> WhatsApp -> Meta API -> Railway
                                      |
                                      v
                              +---------------+
                              |   Whisper     | (transcripcion)
                              +---------------+
                                      |
                                      v
                              +---------------+
                              | Llama 3.3 70B | (respuesta)
                              +---------------+
                                      |
                              +-------+-------+
                              |               |
                         (English)       (Spanish)
                              |               |
                              v               v
                       +----------+    +------------+
                       | PlayAI   |    | Google TTS |
                       | TTS      |    | (es-US)    |
                       +----------+    +------------+
                              |               |
                              v               |
                       +----------+           |
                       |  ffmpeg  |           |
                       | WAV->MP3 |           |
                       +----------+           |
                              |               |
                              +-------+-------+
                                      |
                                      v
                              WhatsApp -> Usuario
```

## Stack Tecnologico

- **Runtime:** Python 3.11
- **Framework:** FastAPI
- **Hosting:** Railway (Docker)
- **LLM:** Groq (Llama 3.3 70B Versatile)
- **STT:** Groq Whisper Large v3 Turbo
- **TTS Ingles:** Groq PlayAI TTS
- **TTS Espanol:** Google Cloud Text-to-Speech (es-US Latino)
- **Vision:** Groq Llama 4 Scout
- **Audio Processing:** ffmpeg (para convertir WAV->MP3)
- **Cache/Memory:** Redis
- **API:** Meta WhatsApp Business API v21.0

## Variables de Entorno

| Variable | Descripcion | Obligatorio |
|----------|-------------|-------------|
| `VERIFY_TOKEN` | Token para verificar webhook de Meta | Si |
| `WHATSAPP_TOKEN` | Token de System User de Meta (permanente) | Si |
| `APP_SECRET` | App Secret de Meta Developers | Si |
| `PHONE_NUMBER_ID` | ID del numero de WhatsApp (**NO es WABA ID**) | Si |
| `GROQ_API_KEY` | API Key de Groq | Si |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Service Account JSON de Google Cloud | Si (para TTS espanol) |
| `REDIS_URL` | URL de Redis (Railway lo provee automatico) | Si |

> **IMPORTANTE:** `PHONE_NUMBER_ID` es el ID del numero, NO el WABA ID.
> - WABA ID: Para suscripciones `/subscribed_apps`
> - Phone Number ID: Para enviar mensajes

## Problemas Comunes y Soluciones

Ver [TROUBLESHOOTING.md](TROUBLESHOOTING.md) para documentacion detallada de errores.

### Resumen Rapido

| Problema | Solucion |
|----------|----------|
| Webhook OK pero mensajes no llegan | POST a `/subscribed_apps` |
| `$PORT` no es integer | Usar `python main.py` |
| Token expira cada 24h | Crear System User |
| PlayAI requiere terminos | Aceptar en Groq Playground |
| WhatsApp no acepta WAV | Convertir a MP3 con ffmpeg |
| ffmpeg no encontrado | Usar Dockerfile con apt-get |

## Estructura del Proyecto

```
loopera-whatsapp-ai-rails/
├── main.py              # App principal FastAPI (~750 lineas)
├── Dockerfile           # Imagen con Python 3.11 + ffmpeg
├── requirements.txt     # Dependencias Python
├── .env.example         # Variables de entorno ejemplo
├── TROUBLESHOOTING.md   # Errores y soluciones detalladas
└── README.md            # Esta documentacion
```

## Configuracion Meta WhatsApp

1. Crear App en [Meta Developers](https://developers.facebook.com/)
2. Agregar producto WhatsApp
3. Configurar Webhook URL: `https://tu-app.railway.app/webhook`
4. Suscribirse al campo `messages`
5. **CRITICO:** Ejecutar POST a `/subscribed_apps` (Shadow Delivery Problem)
6. Crear System User para token permanente

## Deploy en Railway

1. Fork/clone este repo
2. Crear proyecto en Railway
3. Conectar repo de GitHub
4. Agregar Redis addon
5. Configurar variables de entorno
6. Deploy automatico (usa Dockerfile)

## Limites de Groq (Free Tier)

| Modelo | RPM | TPD | Uso |
|--------|-----|-----|-----|
| Llama 3.3 70B | 30 | 100K | Chat principal |
| Whisper Turbo | 20 | 2,000 | Transcripcion |
| PlayAI TTS | 20 | - | Voz ingles |
| Llama 4 Scout | 30 | 500K | Analisis imagenes |

RPM = Requests Per Minute, TPD = Tokens Per Day

## Flujo de Mensajes

### Texto
```
Usuario envia texto -> Llama genera respuesta -> Envia texto
```

### Nota de voz (Ingles)
```
Usuario envia voz -> Whisper transcribe -> Llama responde
-> PlayAI TTS genera WAV -> ffmpeg convierte a MP3 -> Envia nota de voz
```

### Nota de voz (Espanol)
```
Usuario envia voz -> Whisper transcribe -> Llama responde
-> Google TTS genera MP3 directo -> Envia nota de voz
```

### Imagen
```
Usuario envia imagen -> Llama 4 Scout analiza -> Envia texto
```

## Configuracion Google Cloud TTS

1. Crear proyecto en [Google Cloud Console](https://console.cloud.google.com/)
2. Habilitar Cloud Text-to-Speech API
3. Crear Service Account con rol Owner
4. Generar JSON key
5. Pegar JSON completo (minificado) en variable `GOOGLE_APPLICATION_CREDENTIALS_JSON`

## Voces Configuradas

| Idioma | Provider | Voz | Codigo |
|--------|----------|-----|--------|
| Espanol Latino | Google Cloud | Wavenet | es-US-Wavenet-B |
| Ingles | PlayAI (Groq) | Arista | Arista-PlayAI |

## Lecciones Aprendidas

1. **Railway + Dockerfile:** El CMD del Dockerfile funciona, no necesita Procfile
2. **Meta Webhooks:** Siempre ejecutar POST a `/subscribed_apps` despues de verificar
3. **Phone Number ID != WABA ID:** Error comun que causa "Object does not exist"
4. **Audio en WhatsApp:** Solo acepta AAC, MP3, OGG, OPUS, AMR (no WAV)
5. **TTS Multilingue:** Groq PlayAI no tiene espanol, usar Google Cloud
6. **Tokens de Meta:** Siempre crear System User para produccion (token permanente)
7. **$PORT en Docker:** Railway inyecta PORT, leerlo con `os.getenv()` en Python

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/` | Health check con features |
| GET | `/health` | Health check simple |
| GET | `/webhook` | Verificacion de Meta |
| POST | `/webhook` | Recepcion de mensajes |

## Desarrollo Local

```bash
# Clonar
git clone https://github.com/intelguy8000/loopera-whatsapp-ai-rails
cd loopera-whatsapp-ai-rails

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables
cp .env.example .env
# Editar .env con tus valores

# Ejecutar
python main.py

# El bot estara en http://localhost:8000
```

Para probar con WhatsApp necesitas un tunel publico (ngrok, cloudflared).

## Licencia

MIT - Loopera 2026
