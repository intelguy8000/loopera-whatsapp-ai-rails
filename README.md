# Loopera WhatsApp AI Bot

Bot de WhatsApp con IA que procesa texto, imagenes y notas de voz. Responde con voz cuando recibe notas de voz en ingles.

## Features

| Feature | Tecnologia | Status |
|---------|------------|--------|
| Texto -> Texto | Llama 3.3 70B | OK |
| Voz -> Texto | Whisper + Llama | OK |
| Voz (EN) -> Voz (EN) | PlayAI TTS + ffmpeg | OK |
| Imagenes -> Texto | Llama 4 Scout Vision | OK |
| Memoria conversacional | Redis (24h) | OK |
| Multilingue | Deteccion automatica | OK |

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
                                      v
                              +---------------+
                              |  PlayAI TTS   | (genera voz)
                              +---------------+
                                      |
                                      v
                              +---------------+
                              |    ffmpeg     | (WAV -> MP3)
                              +---------------+
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
- **TTS:** Groq PlayAI TTS
- **Vision:** Groq Llama 4 Scout
- **Audio Processing:** ffmpeg
- **Cache/Memory:** Redis
- **API:** Meta WhatsApp Business API

## Variables de Entorno

| Variable | Descripcion | Ejemplo |
|----------|-------------|---------|
| `VERIFY_TOKEN` | Token para verificar webhook | `loopera_railway_2024` |
| `WHATSAPP_TOKEN` | Token de acceso de Meta (System User) | `EAAG...` |
| `APP_SECRET` | App Secret de Meta | `abc123...` |
| `PHONE_NUMBER_ID` | ID del numero de WhatsApp (NO es WABA ID) | `949507764911133` |
| `GROQ_API_KEY` | API Key de Groq | `gsk_...` |
| `REDIS_URL` | URL de Redis (Railway lo provee automatico) | `redis://...` |

> **IMPORTANTE:** `PHONE_NUMBER_ID` es el ID del numero, NO el WABA ID.
> - WABA ID: `1282258597052951` (para suscripciones)
> - Phone Number ID: `949507764911133` (para enviar mensajes)

## Errores Comunes y Soluciones

### 1. Shadow Delivery Problem

**Problema:** Webhook verifica OK pero mensajes no llegan.

**Causa:** Meta no crea automaticamente la suscripcion WABA-to-App desde Oct 2025.

**Solucion:**
```bash
curl -X POST "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" \
  -d "override_callback_uri=https://tu-app.railway.app/webhook" \
  -d "verify_token=tu_verify_token"
```

**Verificar suscripcion:**
```bash
curl "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

### 2. $PORT no se expande en Docker

**Problema:** `Invalid value for '--port': '$PORT' is not a valid integer`

**Causa:** Docker no expande variables de entorno en CMD cuando Railway usa Dockerfile.

**Solucion:** Usar `python main.py` que lee PORT con `os.getenv()`:
```python
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
```

### 3. Token de WhatsApp expira

**Problema:** `Session has expired`

**Solucion:** Crear System User en Meta Business Settings con token permanente:
1. Meta Business Settings > System Users
2. Crear nuevo System User
3. Asignar permisos de WhatsApp
4. Generar token (nunca expira)

### 4. TTS requiere aceptar terminos

**Problema:** `The model 'playai-tts' requires terms acceptance`

**Solucion:** Visitar https://console.groq.com/playground?model=playai-tts y aceptar los terminos.

### 5. WhatsApp no acepta WAV

**Problema:** `Param file must be a file with one of the following types: audio/aac, audio/mp4...`

**Solucion:** Convertir WAV a MP3 con ffmpeg antes de enviar (ya implementado en el bot).

### 6. ffmpeg no encontrado

**Problema:** `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`

**Solucion:** El Dockerfile ya incluye ffmpeg. Si usas Nixpacks, crear `nixpacks.toml`:
```toml
[phases.setup]
nixPkgs = ["ffmpeg"]
```

## Estructura del Proyecto

```
loopera-whatsapp-ai-rails/
├── main.py              # App principal FastAPI (700+ lineas)
├── Dockerfile           # Imagen con Python 3.11 + ffmpeg
├── requirements.txt     # Dependencias Python
├── .env.example         # Variables de entorno ejemplo
├── .gitignore           # Archivos ignorados
└── README.md            # Esta documentacion
```

## Configuracion Meta WhatsApp

1. Crear App en [Meta Developers](https://developers.facebook.com)
2. Agregar producto WhatsApp
3. Configurar Webhook:
   - URL: `https://tu-app.railway.app/webhook`
   - Verify Token: mismo que `VERIFY_TOKEN`
4. Suscribirse a campo `messages`
5. **CRITICO:** Ejecutar POST a `/subscribed_apps` (Shadow Delivery Problem)
6. Crear System User para token permanente

## Deploy en Railway

1. Fork/clone este repo
2. Crear proyecto en [Railway](https://railway.app)
3. Conectar repo de GitHub
4. Agregar Redis addon (opcional, para memoria)
5. Configurar variables de entorno:
   - `VERIFY_TOKEN`
   - `WHATSAPP_TOKEN`
   - `APP_SECRET`
   - `PHONE_NUMBER_ID`
   - `GROQ_API_KEY`
6. Deploy automatico

## Limites de Groq (Free Tier)

| Modelo | RPM | TPD |
|--------|-----|-----|
| Llama 3.3 70B | 30 | 100K |
| Whisper Turbo | 20 | 2,000 |
| PlayAI TTS | 30 | 100K |
| Llama 4 Scout | 30 | 500K |

RPM = Requests Per Minute
TPD = Tokens Per Day

## Flujo de Mensajes

### Texto
```
Usuario envia texto -> Llama genera respuesta -> Envia texto
```

### Nota de voz (Ingles)
```
Usuario envia voz -> Whisper transcribe -> Llama responde
-> PlayAI TTS -> ffmpeg (WAV->MP3) -> Envia nota de voz
```

### Nota de voz (Espanol)
```
Usuario envia voz -> Whisper transcribe -> Llama responde
-> Envia texto (TTS no soporta ES)
```

### Imagen
```
Usuario envia imagen -> Llama 4 Scout analiza -> Envia texto
```

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
# o: venv\Scripts\activate  # Windows

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
