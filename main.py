"""
Loopera WhatsApp Bot - Railway Edition
Webhook handler para WhatsApp Cloud API con soporte Groq (LLM + Whisper + Vision)
"""
import os
import hmac
import hashlib
import logging
import tempfile
import subprocess
import base64
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "loopera-verify-2024")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
APP_SECRET = os.getenv("APP_SECRET", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "949507764911133")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "")

WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"

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

async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribir audio usando Groq Whisper"""
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
    """Detectar idioma del texto (es/en)"""
    spanish_indicators = [
        'hola', 'qué', 'cómo', 'gracias', 'por favor', 'necesito', 'quiero',
        'buenos', 'buenas', 'está', 'dónde', 'cuánto', 'tengo', 'puedo',
        'ayuda', 'información', 'servicio', 'precio', 'cuándo', 'porqué'
    ]
    text_lower = text.lower()
    for word in spanish_indicators:
        if word in text_lower:
            return "es"
    return "en"


def convert_wav_to_mp3(wav_data: bytes) -> bytes | None:
    """Convierte WAV a MP3 usando ffmpeg"""
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
    """Convierte texto a audio usando Groq PlayAI TTS (solo inglés)"""
    if not GROQ_API_KEY:
        return None

    # PlayAI TTS solo soporta inglés
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


async def chat_completion(user_message: str, history: list = None) -> str:
    """Generar respuesta con Groq LLM"""
    if not GROQ_API_KEY:
        return "Bot configurado. Falta GROQ_API_KEY para respuestas inteligentes."

    system_prompt = """You are Loopera's virtual assistant, specialized in AI automation for businesses.

LANGUAGE RULES:
- ALWAYS detect and respond in the SAME language the user writes
- Spanish → respond in Spanish
- English → respond in English
- Portuguese → respond in Portuguese
- French → respond in French
- Any other language → respond in that same language

BUSINESS RULES:
1. ONLY answer about: Loopera services, automation, WhatsApp bots, AI for business
2. Out of scope: "I can only help you with automation topics." (in user's language)
3. NEVER discuss: politics, sports, news, general knowledge
4. If unsure: "Let me connect you with a human advisor." (in user's language)
5. Always identify as Loopera's virtual assistant
6. Keep responses concise (max 3 sentences)"""

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

    system_prompt = """You are Loopera's virtual assistant, specialized in AI automation for businesses.

LANGUAGE RULES:
- ALWAYS detect and respond in the SAME language the user writes
- Spanish → respond in Spanish
- English → respond in English
- Portuguese → respond in Portuguese
- French → respond in French
- Any other language → respond in that same language

BUSINESS RULES:
1. ONLY answer about: Loopera services, automation, WhatsApp bots, AI for business
2. Out of scope: "I can only help you with automation topics." (in user's language)
3. NEVER discuss: politics, sports, news, general knowledge
4. If unsure: "Let me connect you with a human advisor." (in user's language)
5. Always identify as Loopera's virtual assistant
6. Keep responses concise (max 3 sentences)

IMAGE ANALYSIS:
When user sends an image, analyze it in context of automation services."""

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

async def send_whatsapp_message(to: str, text: str):
    """Enviar mensaje de WhatsApp"""
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

                    # 3. Detectar idioma e intentar responder con voz
                    language = detect_language(user_text)
                    voice_sent = False

                    if language == "en":
                        # Intentar enviar respuesta de voz en inglés
                        audio_response = await text_to_speech(response, language)
                        if audio_response:
                            voice_sent = await send_whatsapp_audio(phone, audio_response)

                    # 4. Fallback a texto si TTS falla o es español
                    if not voice_sent:
                        if language == "es":
                            response += "\n\n_(Respuesta de voz disponible solo en inglés)_"
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
    title="Loopera WhatsApp Bot",
    description="Bot de WhatsApp para Loopera - Railway Edition (Text + Audio + Vision)",
    version="1.2.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check principal"""
    return {
        "status": "online",
        "service": "Loopera WhatsApp Bot",
        "version": "1.2.0",
        "features": ["text", "audio", "vision", "tts-en"]
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Iniciando en puerto {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
