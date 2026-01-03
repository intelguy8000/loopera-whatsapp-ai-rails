"""
Conaltura WhatsApp Bot - Cami
=========================================

Bot de WhatsApp con IA para Conaltura Construcción y Vivienda S.A.S.
Agente: "Cami" - Asesor Virtual Inteligente

Funcionalidades:
- Texto -> Texto (Llama 3.3 70B)
- Voz -> Voz ES (Whisper + Llama + Google TTS)
- Imagen -> Texto (Llama 4 Scout Vision)
- Asesoría inmobiliaria con inventario 2025
- Información de subsidios (Mi Casa Ya, regionales)
- Proceso de compra y vinculación fiduciaria

Stack:
- Framework: FastAPI
- LLM: Groq (llama-3.3-70b-versatile)
- STT: Groq Whisper Large v3 Turbo
- TTS: Google Cloud TTS (es-US-Wavenet-B, latino)
- Vision: Groq Llama 4 Scout
- Memory: Redis (24h TTL, 20 mensajes)

Deployment:
- Railway con Dockerfile
- Puerto: leido con os.getenv("PORT") porque Docker no expande $PORT

Cliente: Conaltura Construcción y Vivienda S.A.S.
Desarrollado por: Loopera 2026
"""
import os
import hmac
import hashlib
import logging
import tempfile
import subprocess
import base64
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
from google.cloud import texttospeech
from google.oauth2 import service_account
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACION
# =============================================================================
# Variables de entorno - ver .env.example para documentacion completa
# IMPORTANTE: PHONE_NUMBER_ID != WABA_ID (error comun)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "loopera-verify-2024")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")  # System User token (permanente)
APP_SECRET = os.getenv("APP_SECRET", "")  # Para validar firmas de webhook
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "949507764911133")  # NO es WABA ID
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")  # console.groq.com
REDIS_URL = os.getenv("REDIS_URL", "")  # Railway lo provee automatico

# URL para enviar mensajes - usa Phone Number ID, no WABA ID
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"


def get_google_tts_client():
    """
    Carga cliente de Google TTS desde variable de entorno.
    El JSON de Service Account se pasa como string en GOOGLE_APPLICATION_CREDENTIALS_JSON.
    Esto evita montar archivos en el container.
    """
    credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if credentials_json:
        credentials_dict = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_dict)
        return texttospeech.TextToSpeechClient(credentials=credentials)
    return None

# =============================================================================
# REDIS (OPCIONAL)
# =============================================================================

redis_client = None

async def init_redis():
    """Inicializar conexión Redis si está configurado"""
    global redis_client
    if REDIS_URL:
        try:
            import redis.asyncio as redis
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await redis_client.ping()
            logger.info("Redis conectado")
        except Exception as e:
            logger.warning(f"Redis no disponible: {e}")
            redis_client = None

async def get_conversation_history(phone: str) -> list:
    """Obtener historial de conversación"""
    if not redis_client:
        return []
    try:
        import json
        data = await redis_client.get(f"conv:{phone}")
        return json.loads(data) if data else []
    except:
        return []

async def save_conversation(phone: str, history: list):
    """Guardar historial de conversación"""
    if not redis_client:
        return
    try:
        import json
        # Mantener últimos 20 mensajes
        history = history[-20:]
        await redis_client.setex(f"conv:{phone}", 86400, json.dumps(history))
    except:
        pass

# =============================================================================
# GROQ SERVICE
# =============================================================================
# Servicios de IA usando Groq API (console.groq.com)
# - Whisper: Transcripcion de audio (soporta OGG de WhatsApp)
# - Llama 3.3 70B: Chat principal
# - PlayAI TTS: Text-to-speech en ingles (genera WAV)
# - Llama 4 Scout: Vision/analisis de imagenes

async def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Transcribir audio usando Groq Whisper.
    WhatsApp envia OGG, lo convertimos a MP3 para mejor compatibilidad.
    """
    if not GROQ_API_KEY:
        return "[Audio recibido - Groq no configurado]"

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
        temp_ogg.write(audio_bytes)
        temp_ogg_path = temp_ogg.name

    try:
        temp_mp3_path = temp_ogg_path.replace(".ogg", ".mp3")

        # Convertir OGG a MP3
        result = subprocess.run([
            "ffmpeg", "-i", temp_ogg_path,
            "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1",
            temp_mp3_path, "-y"
        ], capture_output=True, timeout=30)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr.decode()}")
            return "[Error procesando audio]"

        # Transcribir con Groq
        async with httpx.AsyncClient() as client:
            with open(temp_mp3_path, "rb") as f:
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("audio.mp3", f, "audio/mpeg")},
                    data={"model": "whisper-large-v3-turbo"},  # Auto-detect language
                    timeout=60
                )

            if response.status_code == 200:
                return response.json().get("text", "")
            else:
                logger.error(f"Groq Whisper error: {response.text}")
                return "[Error transcribiendo audio]"

    finally:
        Path(temp_ogg_path).unlink(missing_ok=True)
        Path(temp_mp3_path).unlink(missing_ok=True)


def detect_language(text: str) -> str:
    """Detecta si el texto es español o inglés"""
    spanish_words = ['hola', 'qué', 'cómo', 'gracias', 'por favor', 'necesito',
                     'quiero', 'buenos', 'buenas', 'está', 'dónde', 'cuándo',
                     'cuánto', 'puede', 'tienen', 'hacer', 'ayuda', 'información',
                     'servicio', 'precio', 'cuenta', 'bien', 'mucho', 'para']
    text_lower = text.lower()
    spanish_count = sum(1 for word in spanish_words if word in text_lower)
    return "es" if spanish_count >= 1 else "en"


def convert_wav_to_mp3(wav_data: bytes) -> bytes | None:
    """
    Convierte WAV a MP3 usando ffmpeg.
    Necesario porque PlayAI TTS genera WAV pero WhatsApp no lo acepta.
    WhatsApp acepta: AAC, MP3, OGG, OPUS, AMR
    """
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
            wav_file.write(wav_data)
            wav_path = wav_file.name

        mp3_path = wav_path.replace('.wav', '.mp3')

        # Convertir con ffmpeg
        result = subprocess.run([
            'ffmpeg', '-i', wav_path, '-acodec', 'libmp3lame', '-y', mp3_path
        ], capture_output=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr.decode()}")
            return None

        with open(mp3_path, 'rb') as mp3_file:
            mp3_data = mp3_file.read()

        # Limpiar archivos temporales
        Path(wav_path).unlink(missing_ok=True)
        Path(mp3_path).unlink(missing_ok=True)

        return mp3_data
    except Exception as e:
        logger.error(f"Error convirtiendo audio: {e}")
        return None


async def text_to_speech(text: str, language: str = "en") -> bytes | None:
    """
    Text-to-Speech usando Groq PlayAI TTS (solo ingles).
    Genera WAV que luego se convierte a MP3 para WhatsApp.
    Para espanol, usar google_text_to_speech().

    NOTA: Requiere aceptar terminos en console.groq.com/playground?model=playai-tts
    """
    if not GROQ_API_KEY:
        return None

    # PlayAI TTS solo soporta ingles
    if language == "es":
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "playai-tts",
                    "input": text,
                    "voice": "Arista-PlayAI",
                    "response_format": "wav"
                }
            )

            if response.status_code == 200:
                wav_data = response.content
                logger.info(f"TTS generado: {len(wav_data)} bytes WAV")

                # Convertir a MP3 para WhatsApp
                mp3_data = convert_wav_to_mp3(wav_data)
                if mp3_data:
                    logger.info(f"Convertido a MP3: {len(mp3_data)} bytes")
                    return mp3_data
                else:
                    logger.error("Falló conversión WAV->MP3")
                    return None
            else:
                logger.error(f"TTS error: {response.text}")
                return None
    except Exception as e:
        logger.error(f"TTS exception: {e}")
        return None


async def google_text_to_speech(text: str, language: str = "es") -> bytes:
    """
    Text-to-Speech usando Google Cloud TTS.
    Soporta espanol latino (es-US) e ingles (en-US).
    Genera MP3 directamente (no necesita conversion como PlayAI).

    Voces configuradas:
    - Espanol: es-US-Wavenet-B (femenina, latina)
    - Ingles: en-US-Wavenet-F (femenina)

    Requiere GOOGLE_APPLICATION_CREDENTIALS_JSON en variables de entorno.
    """
    try:
        client = get_google_tts_client()
        if not client:
            logger.error("Google TTS client not configured")
            return None

        # Configurar el input
        synthesis_input = texttospeech.SynthesisInput(text=text)

        # Seleccionar voz según idioma
        if language == "es":
            voice = texttospeech.VoiceSelectionParams(
                language_code="es-US",  # Español latino
                name="es-US-Wavenet-B",  # Voz femenina natural
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            )
        else:
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Wavenet-F",
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            )

        # Configurar audio output (MP3 directo, no necesita conversión)
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        # Generar audio
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        logger.info(f"🎵 Google TTS generado: {len(response.audio_content)} bytes")
        return response.audio_content

    except Exception as e:
        logger.error(f"Google TTS error: {e}")
        return None


async def chat_completion(user_message: str, history: list = None) -> str:
    """Generar respuesta con Groq LLM"""
    if not GROQ_API_KEY:
        return "Bot configurado. Falta GROQ_API_KEY para respuestas inteligentes."

    system_prompt = """Eres "Cami", el Asesor Virtual Inteligente de Conaltura Construcción y Vivienda S.A.S.

## IDENTIDAD
- Empresa con +35 años de trayectoria
- Certificada como Empresa B (B-Corp) - compromiso ético y ambiental
- Estrategia VIO: Visión, Innovación, Oportunidad en Sostenibilidad
- Certificaciones EDGE y LEED = ahorro en facturas de servicios
- +600 colaboradores, +3,000 empleos indirectos

## TONO DE VOZ
- Profesional pero cercano y empático
- La compra de vivienda es estresante, sé comprensivo
- Usa emojis moderadamente: 🏡 🌿 📍 ✨
- Tutea al usuario (es Colombia)
- Respuestas concisas (máximo 4 oraciones por mensaje)

## OBJETIVOS
1. PERFILAR: ¿Busca vivienda para vivir, invertir, o escribe desde el exterior?
2. ASESORAR: Resolver dudas sobre proyectos, precios, subsidios
3. CONVERTIR: Lograr que agende visita o deje datos (Nombre, Celular, Email)
4. EDUCAR: Explicar beneficios de sostenibilidad y proceso fiduciario

## INVENTARIO 2025

### VIVIENDA VIS (Interés Social - Aplican Subsidios)
| Proyecto | Ciudad | Desde |
|----------|--------|-------|
| Azzuri | La Estrella | $255M |
| Campura | Medellín | $206M |
| Mosaico | Medellín | Tope VIS |
| Venti | Tocancipá | Tope VIS |
| Zuá | Bogotá | Tope VIS |
| Almendro | Fontibón, Bogotá | $150M+ |
| Amara | Cali | $236M |

### VIVIENDA NO VIS (Sin subsidio, mayor área)
| Proyecto | Ciudad | Área m² | Desde |
|----------|--------|---------|-------|
| Bora | Bello | 56-63 | $298M |
| Catalana | Medellín | 61-77 | $472M |
| Crista | Medellín | 75-88 | $729M |
| Foresta | Envigado | 61-75 | $502M (Certificación EDGE) |
| Polanco | Envigado | 51-110 | $521M |
| Torres del Campo | Rionegro | 60-62 | $434M |
| Canarias | Cajicá | 65 | $325M |

### INVERSIÓN/LUJO (Costa Caribe)
| Proyecto | Ciudad | Área m² | Desde | Especial |
|----------|--------|---------|-------|----------|
| Coralia | Cartagena | 73-88 | $581M | Licencia turística (Airbnb) |
| Diporto | Cartagena | 87-97 | $748M | Vista al mar, muelle privado |

## SUBSIDIOS (Solo para VIS)

### Mi Casa Ya (Nacional)
- Requisito: Ingresos familiares < 4 SMMLV (~$5.7M)
- Requiere Sisbén A1 a D20
- Montos: 20-30 SMMLV ($28M - $42M aprox)

### Subsidios Regionales (SE PUEDEN SUMAR)
- Medellín (Isvimed): $13M-$15M adicionales. Requiere 6 años viviendo en Medellín
- Bogotá: "Mi Casa en Bogotá" 10-30 SMMLV adicionales
- Barranquilla: "Mi Techo Propio" hasta 30 SMMLV
- Cali: "Casa Mía" hasta 30 SMMLV. Requiere 5 años en Cali

### Cajas de Compensación
- Para ingresos < 2 SMMLV
- Se suma con Mi Casa Ya (Concurrencia) = hasta 50 SMMLV total

## PROCESO DE COMPRA

1. SEPARACIÓN: Pago en línea (PSE/Wompi). Monto varía según proyecto ($500K - $2M)
2. VINCULACIÓN FIDUCIARIA: El dinero va a Alianza Fiduciaria (no a Conaltura directo) = SEGURIDAD
3. CUOTA INICIAL: 30% del valor, pagado en cuotas durante construcción
4. CRÉDITO HIPOTECARIO: 70% restante, contra entrega

## COLOMBIANOS EN EL EXTERIOR
- Necesitan APODERADO en Colombia (familiar/amigo) para firmar
- El inmueble queda a nombre del comprador, no del apoderado
- Divisas deben pasar por Comisionista de Bolsa (no giros directos)
- Documentos: W9/W8 BEN (USA), carta laboral, extractos bancarios 3 meses

## SCRIPTS DE RESPUESTA

### Saludo
"¡Hola! 👋 Bienvenido a Conaltura. Soy Cami, tu asesora virtual. Llevamos +35 años construyendo hogares sostenibles en Colombia 🏡🌿

¿Estás buscando vivienda para vivir, para invertir, o nos escribes desde el exterior?"

### Si pregunta por subsidios
"¡Claro! Aceptamos subsidios Mi Casa Ya en proyectos VIS como Azzuri, Venti y Amara.

Para aplicar, tus ingresos familiares no deben superar $5.7 millones. ¿Cumples con este requisito? Así te asesoro mejor 💰"

### Si es inversionista o menciona Airbnb/renta
"Para inversión te recomiendo Coralia en Cartagena 🏖️ Tiene licencia turística para rentas cortas tipo Airbnb. También Almendro en Bogotá por su cercanía al aeropuerto.

¿Te envío más información de alguno?"

### Si escribe desde el exterior
"¡Excelente! Tenemos plan especial para colombianos en el exterior 🌍

Solo necesitas un apoderado (familiar/amigo) en Colombia para firmar, pero el inmueble queda 100% a TU nombre.

¿Te interesa Medellín, Bogotá o la Costa?"

### Si pregunta precios específicos
Usa la tabla de inventario. Si no tienes el dato exacto:
"El precio exacto depende del piso y la vista. Te puedo conectar con un asesor para cotización personalizada. ¿Me compartes tu WhatsApp?"

### Para cerrar/agendar
"Me encantaría que conocieras el proyecto en persona. ¿Qué día te queda bien para visitar la sala de ventas? 📅

También podemos hacer videollamada si estás lejos."

### Si hay queja o problema
"Entiendo tu inquietud y lamento el inconveniente. Para darte una solución concreta, por favor escribe a experienciadelcliente@conaltura.com o al formulario PQRS.

¿Hay algo más en lo que pueda ayudarte?"

## INFORMACIÓN DE CONTACTO
- Medellín: (604) 266 22 77 - Calle 5A #39-194, Piso 5, Torre Dinners
- Bogotá: (601) 432 1600 - Carrera 19 #82-85, Of 704, Country Office
- Barranquilla: 312 469 0731 - Carrera 51B No. 80-58, Of 1006

## REGLAS ESTRICTAS
1. NUNCA inventes precios. Si no sabes, da rango o pide conectar con asesor
2. NUNCA garantices subsidios - dependen del gobierno
3. SIEMPRE intenta capturar: Nombre, Celular, Ciudad de interés
4. Si preguntan por garantías: 10 años estructura, 1 año acabados
5. Portal propietarios: site.conaltura.com/mi-hogar/

## IDIOMA
- Solo español colombiano
- Si escriben en inglés, responde en español pero amablemente"""

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 500
            },
            timeout=30
        )

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Groq LLM error: {response.text}")
            return "Disculpa, tuve un problema. ¿Podrías repetir?"


async def analyze_image(image_base64: str, media_type: str, caption: str, history: list = None) -> str:
    """Analizar imagen usando Groq Llama Vision"""
    if not GROQ_API_KEY:
        return "No puedo analizar imágenes sin GROQ_API_KEY configurado."

    system_prompt = """Eres "Cami", el Asesor Virtual de Conaltura Construcción y Vivienda S.A.S.

## CONTEXTO
- Empresa colombiana con +35 años construyendo vivienda
- Certificada como Empresa B (B-Corp)
- Proyectos en Medellín, Bogotá, Cali, Cartagena y más

## ANÁLISIS DE IMÁGENES
Cuando el usuario envía una imagen, analízala así:
- Si es un render/plano: Describe el proyecto y pregunta si quiere más información
- Si es un documento (cédula, extractos): Confirma recepción y explica siguiente paso
- Si es una ubicación/mapa: Identifica zona y sugiere proyectos cercanos
- Si es un comprobante de pago: Confirma y sugiere contactar asesor para verificación
- Si no está relacionada con vivienda: Amablemente redirige a temas inmobiliarios

## TONO
- Profesional pero cercano
- Usa emojis moderadamente: 🏡 🌿 📍
- Solo español colombiano
- Respuestas concisas (máximo 3 oraciones)

## OBJETIVO
Siempre intenta capturar datos del cliente o agendar visita."""

    # Construir mensajes con historial
    messages = [{"role": "system", "content": system_prompt}]

    # Agregar últimos 6 mensajes de historial para contexto
    if history:
        messages.extend(history[-6:])

    # Agregar mensaje con imagen
    user_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{image_base64}"
            }
        },
        {
            "type": "text",
            "text": caption if caption else "¿Qué ves en esta imagen? Descríbela detalladamente."
        }
    ]
    messages.append({"role": "user", "content": user_content})

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 500
            }
        )

        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            logger.error(f"Groq Vision error: {response.text}")
            return "No pude analizar la imagen. ¿Podrías enviarla de nuevo?"


# =============================================================================
# WHATSAPP SERVICE
# =============================================================================
# Funciones para interactuar con Meta WhatsApp Cloud API v21.0
# Documentacion: https://developers.facebook.com/docs/whatsapp/cloud-api/
#
# IMPORTANTE: Usar PHONE_NUMBER_ID (no WABA_ID) para enviar mensajes
# Si obtienes "Object does not exist", verificar que usas el ID correcto

async def send_whatsapp_message(to: str, text: str):
    """Enviar mensaje de texto por WhatsApp"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            WHATSAPP_API_URL,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text}
            },
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f"WhatsApp send error: {response.status_code} - {response.text}")
        else:
            logger.info(f"Mensaje enviado a {to}")

        return response


async def send_whatsapp_audio(to: str, audio_data: bytes) -> bool:
    """Enviar nota de voz por WhatsApp"""
    upload_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Subir audio a Meta
        response = await client.post(
            upload_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            data={"messaging_product": "whatsapp", "type": "audio/mpeg"},
            files={"file": ("audio.mp3", audio_data, "audio/mpeg")}
        )

        if response.status_code != 200:
            logger.error(f"Audio upload error: {response.text}")
            return False

        media_id = response.json().get("id")
        if not media_id:
            logger.error("No media_id in upload response")
            return False

        logger.info(f"Audio subido: media_id={media_id}")

        # 2. Enviar mensaje con audio
        send_response = await client.post(
            WHATSAPP_API_URL,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "audio",
                "audio": {"id": media_id}
            }
        )

        if send_response.status_code == 200:
            logger.info(f"Nota de voz enviada a {to}")
            return True
        else:
            logger.error(f"Audio send error: {send_response.text}")
            return False


async def download_media(media_id: str) -> bytes | None:
    """Descargar archivo multimedia de WhatsApp"""
    async with httpx.AsyncClient() as client:
        # Obtener URL del media
        response = await client.get(
            f"https://graph.facebook.com/v21.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30
        )

        if response.status_code != 200:
            return None

        media_url = response.json().get("url")
        if not media_url:
            return None

        # Descargar archivo
        media_response = await client.get(
            media_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=60
        )

        return media_response.content if media_response.status_code == 200 else None


async def mark_as_read(message_id: str):
    """Marcar mensaje como leído"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                WHATSAPP_API_URL,
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id
                },
                timeout=10
            )
    except:
        pass

# =============================================================================
# MESSAGE PROCESSING
# =============================================================================

async def process_message(phone: str, message: dict, message_type: str, message_id: str):
    """Procesar mensaje en background"""
    try:
        await mark_as_read(message_id)

        # Extraer contenido
        if message_type == "text":
            user_text = message.get("text", {}).get("body", "")
        elif message_type == "audio":
            # Procesar nota de voz con respuesta de voz (si es inglés)
            audio_id = message.get("audio", {}).get("id")
            if audio_id:
                logger.info(f"Procesando nota de voz {audio_id}")
                audio_bytes = await download_media(audio_id)
                if audio_bytes:
                    # 1. Transcribir audio
                    user_text = await transcribe_audio(audio_bytes)
                    logger.info(f"Transcripción: {user_text[:100]}...")

                    if not user_text or user_text.startswith("["):
                        await send_whatsapp_message(phone, "No pude entender tu mensaje de voz. ¿Podrías repetirlo?")
                        return

                    # 2. Generar respuesta
                    history = await get_conversation_history(phone)
                    response = await chat_completion(user_text, history)
                    logger.info(f"Respuesta: {response[:100]}...")

                    # 3. Detectar idioma y generar respuesta de voz
                    language = detect_language(user_text)
                    logger.info(f"🌐 Idioma detectado: {language}")

                    audio_response = None

                    if language == "es":
                        # Usar Google TTS para español
                        logger.info("🔊 Generando respuesta de voz en español (Google TTS)...")
                        audio_response = await google_text_to_speech(response, "es")
                    else:
                        # Usar PlayAI TTS para inglés
                        logger.info("🔊 Generando respuesta de voz en inglés (PlayAI TTS)...")
                        audio_response = await text_to_speech(response)

                    # 4. Enviar audio si se generó correctamente
                    if audio_response:
                        success = await send_whatsapp_audio(phone, audio_response)
                        if not success:
                            logger.warning("Falló envío de audio, enviando texto...")
                            await send_whatsapp_message(phone, response)
                    else:
                        # Fallback a texto
                        await send_whatsapp_message(phone, response)

                    # 5. Guardar en historial
                    history.append({"role": "user", "content": f"[Audio] {user_text}"})
                    history.append({"role": "assistant", "content": response})
                    await save_conversation(phone, history)
                    return
                else:
                    await send_whatsapp_message(phone, "No pude descargar tu mensaje de voz. ¿Podrías enviarlo de nuevo?")
                    return
            else:
                await send_whatsapp_message(phone, "No pude procesar tu mensaje de voz. ¿Podrías enviarlo de nuevo?")
                return
        elif message_type == "image":
            # Procesar imagen con Groq Vision
            image_id = message.get("image", {}).get("id")
            caption = message.get("image", {}).get("caption", "")
            mime_type = message.get("image", {}).get("mime_type", "image/jpeg")

            if image_id:
                logger.info(f"Procesando imagen {image_id}")
                image_bytes = await download_media(image_id)
                if image_bytes:
                    # Convertir a base64
                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                    logger.info(f"Imagen descargada: {len(image_bytes)} bytes, tipo: {mime_type}")

                    # Obtener historial y analizar imagen
                    history = await get_conversation_history(phone)
                    response = await analyze_image(image_base64, mime_type, caption, history)

                    logger.info(f"Respuesta Vision: {response[:100]}...")

                    # Enviar respuesta
                    await send_whatsapp_message(phone, response)

                    # Guardar en historial (texto descriptivo para la imagen)
                    user_text_for_history = f"[Imagen enviada]{': ' + caption if caption else ''}"
                    history.append({"role": "user", "content": user_text_for_history})
                    history.append({"role": "assistant", "content": response})
                    await save_conversation(phone, history)
                    return
                else:
                    await send_whatsapp_message(phone, "No pude descargar la imagen. ¿Podrías enviarla de nuevo?")
                    return
            else:
                await send_whatsapp_message(phone, "No pude procesar la imagen. ¿Podrías enviarla de nuevo?")
                return
        else:
            user_text = f"[{message_type} recibido]"

        if not user_text:
            await send_whatsapp_message(phone, "No pude procesar ese mensaje. ¿Podrías escribirme?")
            return

        logger.info(f"Mensaje de {phone}: {user_text[:100]}")

        # Obtener historial y generar respuesta
        history = await get_conversation_history(phone)
        response = await chat_completion(user_text, history)

        logger.info(f"Respuesta: {response[:100]}")

        # Enviar respuesta
        await send_whatsapp_message(phone, response)

        # Guardar en historial
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response})
        await save_conversation(phone, history)

    except Exception as e:
        logger.error(f"Error procesando mensaje de {phone}: {e}")
        try:
            await send_whatsapp_message(phone, "Disculpa, tuve un problema. ¿Podrías intentar de nuevo?")
        except:
            pass

# =============================================================================
# FASTAPI APP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de la aplicación"""
    logger.info("Iniciando Loopera WhatsApp Bot...")
    await init_redis()
    logger.info(f"Phone Number ID: {PHONE_NUMBER_ID}")
    logger.info(f"Groq configurado: {'Si' if GROQ_API_KEY else 'No'}")
    logger.info(f"Vision habilitado: {'Si' if GROQ_API_KEY else 'No'}")
    yield
    logger.info("Cerrando bot...")


app = FastAPI(
    title="Conaltura WhatsApp Bot",
    description="Cami - Asesor Virtual de Conaltura Construcción y Vivienda",
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check principal"""
    return {
        "status": "online",
        "service": "Conaltura WhatsApp Bot",
        "agent": "Cami",
        "version": "2.0.0",
        "features": ["text", "audio", "vision", "real-estate"],
        "tts": ["google-es"]
    }


@app.get("/health")
async def health():
    """Health check para Railway"""
    return {"status": "healthy"}


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Verificación del webhook de Meta"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    logger.info(f"Verificación webhook: mode={mode}, token={token[:10]}...")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verificado correctamente")
        return PlainTextResponse(content=challenge)

    logger.warning("Verificación de webhook fallida")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibir mensajes de WhatsApp"""
    logger.info("POST /webhook recibido")

    try:
        body = await request.json()
        logger.info(f"Body: {str(body)[:500]}")

        # Extraer mensaje
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            logger.info("Webhook sin mensajes (status update)")
            return {"status": "ok"}

        message = messages[0]
        phone = message.get("from")
        message_id = message.get("id")
        message_type = message.get("type")

        logger.info(f"Mensaje de {phone} - Tipo: {message_type}")

        # Procesar en background
        background_tasks.add_task(
            process_message,
            phone=phone,
            message=message,
            message_type=message_type,
            message_id=message_id
        )

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return {"status": "ok"}


# =============================================================================
# MAIN
# =============================================================================
# IMPORTANTE: Usamos os.getenv("PORT") porque Docker no expande $PORT
# en la directiva CMD. Railway inyecta PORT en runtime.
# Por eso Dockerfile usa: CMD ["python", "main.py"]
# Ver TROUBLESHOOTING.md seccion "$PORT no se expande en Docker"

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Railway inyecta PORT
    logger.info(f"Iniciando en puerto {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
