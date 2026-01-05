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
- TTS: Google Cloud TTS (es-US-Wavenet-D, latino, fallback)
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
import asyncio
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

# ElevenLabs TTS (alta calidad)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ES = "b2htR0pMe28pYwCY9gnP"  # Voz latina para español
ELEVENLABS_VOICE_EN = "1SM7GgM6IMuvQlz2BwM3"  # Voz profesional para inglés

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
# ACTIVOS DIGITALES DE PROYECTOS
# =============================================================================
# URLs reales de imágenes y brochures de Conaltura

PROJECT_ASSETS = {
    "crista": {
        "nombre": "Crista",
        "ciudad": "Medellín - Laureles",
        "precio": "Desde $729 millones de pesos colombianos",
        "area": "75-88 m²",
        "tipo": "imagen",
        "render": "https://conaltura.com/wp-content/uploads/2025/01/FACHADA-2.jpg",
        "planta": "https://conaltura.com/wp-content/uploads/2025/01/165-TIPO-A-83.08m2.jpg",
        "zonas": "https://conaltura.com/wp-content/uploads/2025/01/165-Mesa-de-trabajo-58-copia-17.jpg",
        "url_proyecto": "https://conaltura.com/producto/crista/"
    },
    "foresta": {
        "nombre": "Foresta",
        "ciudad": "Envigado - Vía Las Antillas",
        "precio": "Desde $502 millones de pesos colombianos",
        "area": "61-75 m²",
        "tipo": "imagen",
        "render": "https://conaltura.com/wp-content/uploads/2025/01/8-Mesa-de-trabajo-58-copia-21.jpg",
        "planta": "https://conaltura.com/wp-content/uploads/2025/01/8-TIPO-A-75.OM2-TORRE-3.jpg",
        "zonas": "https://conaltura.com/wp-content/uploads/2025/01/8-Mesa-de-trabajo-58-copia-28.jpg",
        "url_proyecto": "https://conaltura.com/producto/foresta/"
    },
    "canarias": {
        "nombre": "Canarias",
        "ciudad": "Cajicá",
        "precio": "Desde $325 millones de pesos colombianos",
        "area": "65 m²",
        "tipo": "imagen",
        "render": "https://conaltura.com/wp-content/uploads/2024/12/FACHADA-1.jpg",
        "planta": "https://conaltura.com/wp-content/uploads/2024/12/166-TIPO-S-65.48-M2.jpg",
        "zonas": "https://conaltura.com/wp-content/uploads/2024/12/166-Mesa-de-trabajo-58-copia-20.jpg",
        "url_proyecto": "https://conaltura.com/producto/canarias/"
    },
    "azzuri": {
        "nombre": "Azzuri",
        "ciudad": "La Estrella",
        "precio": "Desde $255 millones de pesos colombianos",
        "area": "51 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/04/1924-BROCHURE-FINAL_AZZURI-V1-BAJA_compressed.pdf",
        "url_proyecto": "https://conaltura.com/producto/azzuri/"
    },
    "polanco": {
        "nombre": "Polanco",
        "ciudad": "Envigado - Av. El Poblado",
        "precio": "Desde $521 millones de pesos colombianos",
        "area": "51-110 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/04/1826-BROCHURE-POLANCO_compressed.pdf",
        "url_proyecto": "https://conaltura.com/producto/polanco/"
    },
    "bora": {
        "nombre": "Bora",
        "ciudad": "Bello",
        "precio": "Desde $298 millones de pesos colombianos",
        "area": "56-63 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/13-BROCHURE%20BORA_2024.pdf",
        "url_proyecto": "https://conaltura.com/producto/bora/"
    },
    "campura": {
        "nombre": "Campura",
        "ciudad": "Medellín - Robledo",
        "precio": "Desde $206 millones de pesos colombianos (VIS)",
        "area": "Variable",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/1829-Brochure%20digital%20Campura_nov23%20PDF.pdf",
        "url_proyecto": "https://conaltura.com/producto/campura/"
    },
    "zua": {
        "nombre": "Zuá",
        "ciudad": "Zipaquirá",
        "precio": "Desde $180 millones de pesos colombianos (VIS)",
        "area": "49-55 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/1900-BROCHURE%20DIGITAL%20ZUA%20CORAL.pdf",
        "url_proyecto": "https://conaltura.com/producto/zua/"
    },
    "amara": {
        "nombre": "Amara",
        "ciudad": "Cali - Ciudad Paraíso",
        "precio": "Desde $236 millones de pesos colombianos",
        "area": "55 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/1908-MRCD_BROCHURE%20AMARA%202024.pdf",
        "url_proyecto": "https://conaltura.com/producto/amara/"
    },
    "diporto": {
        "nombre": "Diporto",
        "ciudad": "Cartagena - Serena del Mar",
        "precio": "Desde $748 millones de pesos colombianos",
        "area": "87-97 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/1881-DIPORTO%20BROCHURE.pdf",
        "url_proyecto": "https://conaltura.com/producto/diporto/"
    },
    "coralia": {
        "nombre": "Coralia",
        "ciudad": "Cartagena - Serena del Mar",
        "precio": "Desde $581 millones de pesos colombianos",
        "area": "73-88 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/1873-BROCHURE%20DIGITAL%20CORALIA%20V12-comp..pdf",
        "url_proyecto": "https://conaltura.com/producto/coralia/"
    },
    "torres_del_campo": {
        "nombre": "Torres del Campo",
        "ciudad": "Rionegro",
        "precio": "Desde $434 millones de pesos colombianos",
        "area": "60-62 m²",
        "tipo": "documento",
        "brochure": "https://conaltura.com/wp-content/uploads/2025/01/62-Brochure%20digital%20Torres%20del%20Campo%20nov23_2.pdf",
        "url_proyecto": "https://conaltura.com/producto/torres-del-campo/"
    },
    "meety": {
        "nombre": "Meety Suites",
        "ciudad": "Bogotá - Centro Internacional",
        "precio": "Inversión con 13% rentabilidad",
        "area": "24-42 m²",
        "tipo": "link",
        "url_proyecto": "https://conaltura.com/producto/meety-suites/"
    }
}

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
    Text-to-Speech usando Google Cloud TTS (fallback si ElevenLabs falla).
    Soporta espanol latino (es-US) e ingles (en-US).
    Genera MP3 directamente.

    Voces configuradas (Wavenet):
    - Espanol: es-US-Wavenet-D (femenina, latina)
    - Ingles: en-US-Wavenet-D (femenina)

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
            logger.info("🔊 Usando Google TTS con voz: es-US-Wavenet-D")
            voice = texttospeech.VoiceSelectionParams(
                language_code="es-US",  # Español latino
                name="es-US-Wavenet-D",  # Voz Wavenet femenina
                ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
            )
        else:
            logger.info("🔊 Usando Google TTS con voz: en-US-Wavenet-D")
            voice = texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name="en-US-Wavenet-D",  # Voz Wavenet en inglés
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


async def elevenlabs_text_to_speech(text: str, language: str = "es") -> bytes | None:
    """
    Text-to-Speech usando ElevenLabs (alta calidad).
    Usa el modelo eleven_multilingual_v2 con voz según idioma.
    Genera MP3 directamente.

    Voces:
    - Español: ELEVENLABS_VOICE_ES (latina femenina)
    - Inglés: ELEVENLABS_VOICE_EN (profesional femenina)

    Requiere ELEVENLABS_API_KEY en variables de entorno.
    """
    try:
        if not ELEVENLABS_API_KEY:
            logger.warning("ELEVENLABS_API_KEY no configurada")
            return None

        # Seleccionar voz según idioma
        voice_id = ELEVENLABS_VOICE_ES if language == "es" else ELEVENLABS_VOICE_EN
        logger.info(f"🎙️ ElevenLabs usando voz: {'Latina (ES)' if language == 'es' else 'Profesional (EN)'}")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }

        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.5,
                "use_speaker_boost": True
            }
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=data)

            if response.status_code == 200:
                logger.info(f"🎵 ElevenLabs TTS generado: {len(response.content)} bytes ({language.upper()})")
                return response.content  # Ya viene en MP3, no necesita conversión
            else:
                logger.error(f"ElevenLabs error: {response.status_code} - {response.text}")
                return None

    except Exception as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        return None


async def chat_completion(user_message: str, history: list = None) -> str:
    """Generar respuesta con Groq LLM"""
    if not GROQ_API_KEY:
        return "Bot configurado. Falta GROQ_API_KEY para respuestas inteligentes."

    system_prompt = """Eres "Cami", Asesora Virtual con Inteligencia Artificial de Conaltura Construcción y Vivienda S.A.S.

## ⚠️ REGLAS INNEGOCIABLES - NUNCA VIOLAR ⚠️

Estas reglas son OBLIGATORIAS en CADA interacción. No importa el contexto, SIEMPRE se cumplen:

### REGLA 1: SIEMPRE PEDIR EL NOMBRE
- En el PRIMER mensaje de cualquier conversación, DEBES pedir el nombre del usuario
- Formato: Responde a su pregunta/saludo + pregunta su nombre
- Ejemplo: "¡Hola! Qué gusto saludarte 👋 Soy Cami, tu asesora virtual con IA de Conaltura. [respuesta breve a su consulta]. Para atenderte mejor, ¿me compartes tu nombre?"
- Si ya sabes el nombre (lo mencionaron antes), úsalo: "¡Hola [Nombre]! ¿En qué te puedo ayudar hoy?"
- NUNCA respondas sin intentar obtener el nombre en la primera interacción

### REGLA 2: VOZ SE RESPONDE CON VOZ
- Si el usuario envía una NOTA DE VOZ, SIEMPRE debes responder con NOTA DE VOZ
- El sistema detectará automáticamente las notas de voz y generará audio
- En tu respuesta, habla de forma natural y conversacional (será convertida a audio)
- NUNCA respondas con texto largo si recibiste una nota de voz

### REGLA 3: MONEDA EN PESOS COLOMBIANOS
- TODOS los precios son en PESOS COLOMBIANOS (COP)
- SIEMPRE di "millones de pesos" o "pesos colombianos"
- NUNCA JAMÁS digas "dólares" - esta palabra está PROHIBIDA
- Ejemplo correcto: "desde 255 millones de pesos colombianos"

### REGLA 4: IDENTIDAD DE IA
- SIEMPRE te presentas como "Cami, asesora virtual con inteligencia artificial de Conaltura"
- Si preguntan si eres robot/IA, confirmas con naturalidad y ofreces conectar con humano si prefieren

---

## SOBRE CONALTURA
- Empresa con +35 años de trayectoria
- Certificada como Empresa B (B-Corp) - compromiso ético y ambiental
- Certificaciones EDGE y LEED = ahorro en facturas de servicios

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
| Proyecto | Ciudad | Desde (Millones COP) |
|----------|--------|----------------------|
| Azzuri | La Estrella | $255 millones |
| Campura | Medellín | $206 millones |
| Mosaico | Medellín | Tope VIS |
| Venti | Tocancipá | Tope VIS |
| Zuá | Zipaquirá | $180 millones |
| Almendro | Fontibón, Bogotá | $150 millones+ |
| Amara | Cali | $236 millones |

### VIVIENDA NO VIS (Sin subsidio, mayor área)
| Proyecto | Ciudad | Área m² | Desde (Millones COP) |
|----------|--------|---------|----------------------|
| Bora | Bello | 56-63 | $298 millones |
| Catalana | Medellín | 61-77 | $472 millones |
| Crista | Medellín - Laureles | 75-88 | $729 millones |
| Foresta | Envigado | 61-75 | $502 millones (EDGE) |
| Polanco | Envigado | 51-110 | $521 millones |
| Torres del Campo | Rionegro | 60-62 | $434 millones |
| Canarias | Cajicá | 65 | $325 millones |

### INVERSIÓN/LUJO (Costa Caribe)
| Proyecto | Ciudad | Área m² | Desde (Millones COP) | Especial |
|----------|--------|---------|----------------------|----------|
| Coralia | Cartagena | 73-88 | $581 millones | Licencia turística (Airbnb) |
| Diporto | Cartagena | 87-97 | $748 millones | Vista al mar, muelle privado |
| Meety Suites | Bogotá Centro | 24-42 | Inversión 13% rentabilidad | Renta hotelera |

## SUBSIDIOS (Solo para VIS) - Montos en PESOS COLOMBIANOS

### Mi Casa Ya (Nacional)
- Requisito: Ingresos familiares < 4 SMMLV (~$5.7 millones de pesos)
- Requiere Sisbén A1 a D20
- Montos: 20-30 SMMLV ($28-42 millones de pesos aprox)

### Subsidios Regionales (SE PUEDEN SUMAR)
- Medellín (Isvimed): $13-15 millones adicionales. Requiere 6 años en Medellín
- Bogotá: "Mi Casa en Bogotá" 10-30 SMMLV adicionales
- Barranquilla: "Mi Techo Propio" hasta 30 SMMLV
- Cali: "Casa Mía" hasta 30 SMMLV. Requiere 5 años en Cali

## PROCESO DE COMPRA

1. SEPARACIÓN: Pago en línea (PSE/Wompi). $500 mil - $2 millones de pesos
2. VINCULACIÓN FIDUCIARIA: Dinero va a Alianza Fiduciaria = SEGURIDAD
3. CUOTA INICIAL: 30% del valor, pagado en cuotas durante construcción
4. CRÉDITO HIPOTECARIO: 70% restante, contra entrega

## COLOMBIANOS EN EL EXTERIOR
- Necesitan APODERADO en Colombia (familiar/amigo) para firmar
- El inmueble queda a nombre del comprador, no del apoderado
- Divisas deben pasar por Comisionista de Bolsa (no giros directos)
- Documentos: W9/W8 BEN (USA), carta laboral, extractos bancarios 3 meses

## ACTIVOS VISUALES
- Si el usuario pide "ver", "fotos", "imágenes", "brochure" de un proyecto, el sistema enviará automáticamente el material
- Cuando envíes info de un proyecto, menciona: "Te envío el brochure/imágenes para que lo conozcas mejor 🏡"
- Si no especifica proyecto, pregunta: "¿De qué proyecto te gustaría recibir información visual?"
- Proyectos con imágenes directas: Crista, Foresta, Canarias
- Proyectos con brochure PDF: Azzuri, Polanco, Bora, Campura, Zuá, Amara, Diporto, Coralia, Torres del Campo

## SCRIPTS DE RESPUESTA

### Saludo (Primera interacción)
"¡Hola! 👋 Soy Cami, tu asesora virtual con inteligencia artificial de Conaltura.

Estoy aquí para ayudarte a encontrar tu hogar ideal. Llevamos +35 años construyendo hogares sostenibles en Colombia 🏡🌿

¿Estás buscando vivienda para vivir, para invertir, o nos escribes desde el exterior?"

### Si pregunta si es robot/IA
"Sí, soy Cami, una asesora virtual con inteligencia artificial. Estoy entrenada para ayudarte como lo haría un asesor humano. Si prefieres hablar con una persona, te puedo conectar con gusto. 🤖✨"

### Si pregunta por subsidios
"¡Claro! Aceptamos subsidios Mi Casa Ya en proyectos VIS como Azzuri, Zuá y Amara.

Para aplicar, tus ingresos familiares no deben superar 5.7 millones de pesos. ¿Cumples con este requisito? Así te asesoro mejor 💰"

### Si es inversionista o menciona Airbnb/renta
"Para inversión te recomiendo Coralia en Cartagena 🏖️ Tiene licencia turística para rentas cortas tipo Airbnb. Desde 581 millones de pesos colombianos.

¿Te envío el brochure con más detalles?"

### Si escribe desde el exterior
"¡Excelente! Tenemos plan especial para colombianos en el exterior 🌍

Solo necesitas un apoderado (familiar/amigo) en Colombia para firmar, pero el inmueble queda 100% a TU nombre.

¿Te interesa Medellín, Bogotá o la Costa?"

### Si pregunta precios específicos
Usa la tabla de inventario. SIEMPRE menciona que son PESOS COLOMBIANOS.
"El precio exacto depende del piso y la vista. Te puedo conectar con un asesor para cotización personalizada. ¿Me compartes tu WhatsApp?"

### Para cerrar/agendar
"Me encantaría que conocieras el proyecto en persona. ¿Qué día te queda bien para visitar la sala de ventas? 📅

También podemos hacer videollamada si estás lejos."

### Si hay queja o problema
"Entiendo tu inquietud y lamento el inconveniente. Por favor escribe a experienciadelcliente@conaltura.com

¿Hay algo más en lo que pueda ayudarte?"

## INFORMACIÓN DE CONTACTO
- Medellín: (604) 266 22 77 - Calle 5A #39-194, Piso 5, Torre Dinners
- Bogotá: (601) 432 1600 - Carrera 19 #82-85, Of 704, Country Office
- Barranquilla: 312 469 0731 - Carrera 51B No. 80-58, Of 1006

## REGLAS ESTRICTAS
1. NUNCA inventes precios. Si no sabes, da rango o pide conectar con asesor
2. NUNCA garantices subsidios - dependen del gobierno
3. SIEMPRE menciona PESOS COLOMBIANOS, NUNCA dólares
4. SIEMPRE intenta capturar: Nombre, Celular, Ciudad de interés
5. Si preguntan por garantías: 10 años estructura, 1 año acabados
6. Portal propietarios: site.conaltura.com/mi-hogar/

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


async def send_whatsapp_image(to: str, image_url: str, caption: str = "") -> bool:
    """Envía imagen por WhatsApp usando URL pública"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
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
                    "type": "image",
                    "image": {
                        "link": image_url,
                        "caption": caption
                    }
                }
            )
            if response.status_code == 200:
                logger.info(f"🖼️ Imagen enviada a {to}")
                return True
            logger.error(f"Error enviando imagen: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error enviando imagen: {e}")
        return False


async def send_whatsapp_document(to: str, document_url: str, filename: str, caption: str = "") -> bool:
    """Envía documento PDF por WhatsApp"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
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
                    "type": "document",
                    "document": {
                        "link": document_url,
                        "caption": caption,
                        "filename": filename
                    }
                }
            )
            if response.status_code == 200:
                logger.info(f"📄 Documento enviado a {to}")
                return True
            logger.error(f"Error enviando documento: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error enviando documento: {e}")
        return False


def detect_project_request(text: str) -> str | None:
    """Detecta si el usuario pide info/imágenes de un proyecto específico"""
    text_lower = text.lower()

    # Palabras que indican solicitud de contenido visual
    visual_keywords = ['imagen', 'imágenes', 'foto', 'fotos', 'ver', 'muéstrame',
                       'muestrame', 'enseñame', 'enséñame', 'como se ve', 'cómo se ve',
                       'render', 'brochure', 'catálogo', 'catalogo', 'información',
                       'info', 'planta', 'plantas', 'distribución']

    wants_visual = any(keyword in text_lower for keyword in visual_keywords)

    if not wants_visual:
        return None

    # Mapeo de nombres de proyecto (incluyendo variaciones)
    project_mappings = {
        'crista': 'crista',
        'foresta': 'foresta',
        'canarias': 'canarias',
        'azzuri': 'azzuri',
        'azuri': 'azzuri',
        'polanco': 'polanco',
        'bora': 'bora',
        'campura': 'campura',
        'zua': 'zua',
        'zuá': 'zua',
        'amara': 'amara',
        'diporto': 'diporto',
        'coralia': 'coralia',
        'torres del campo': 'torres_del_campo',
        'torredelcampo': 'torres_del_campo',
        'meety': 'meety',
        'meety suites': 'meety'
    }

    for name, key in project_mappings.items():
        if name in text_lower:
            return key

    # Detectar por ciudad
    city_mappings = {
        'cartagena': 'coralia',
        'serena del mar': 'coralia',
        'cajica': 'canarias',
        'cajicá': 'canarias',
        'la estrella': 'azzuri',
        'envigado': 'foresta',
        'laureles': 'crista',
        'bello': 'bora',
        'rionegro': 'torres_del_campo',
        'zipaquira': 'zua',
        'zipaquirá': 'zua',
        'cali': 'amara',
        'robledo': 'campura'
    }

    for city, project in city_mappings.items():
        if city in text_lower:
            return project

    return "general"


async def send_project_assets(to: str, project_key: str) -> bool:
    """Envía los activos visuales de un proyecto"""
    project = PROJECT_ASSETS.get(project_key)
    if not project:
        return False

    if project["tipo"] == "imagen":
        # Enviar imagen del render
        caption = f"🏡 {project['nombre']} - {project['ciudad']}\n\n💰 {project['precio']}\n📐 Áreas: {project['area']}\n\n🔗 Más info: {project['url_proyecto']}"
        await send_whatsapp_image(to, project["render"], caption)
        return True

    elif project["tipo"] == "documento":
        # Enviar brochure PDF
        caption = f"📋 Brochure {project['nombre']} - {project['ciudad']}\n\n💰 {project['precio']}\n📐 Áreas: {project['area']}"
        filename = f"Brochure_{project['nombre']}_Conaltura.pdf"
        await send_whatsapp_document(to, project["brochure"], filename, caption)
        return True

    elif project["tipo"] == "link":
        # Solo enviar link
        await send_whatsapp_message(to, f"🏡 Conoce {project['nombre']} aquí:\n{project['url_proyecto']}")
        return True

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
            # ===== REGLA INNEGOCIABLE: VOZ SE RESPONDE CON VOZ =====
            audio_id = message.get("audio", {}).get("id")
            if audio_id:
                logger.info(f"🎤 Procesando nota de voz de {phone} - SIEMPRE responderemos con voz")
                audio_bytes = await download_media(audio_id)
                if audio_bytes:
                    # 1. Transcribir audio
                    user_text = await transcribe_audio(audio_bytes)
                    logger.info(f"📝 Transcripción: {user_text[:100]}...")

                    if not user_text or user_text.startswith("["):
                        await send_whatsapp_message(phone, "No pude entender tu mensaje de voz. ¿Podrías repetirlo?")
                        return

                    # 2. Generar respuesta
                    history = await get_conversation_history(phone)
                    response = await chat_completion(user_text, history)
                    logger.info(f"💬 Respuesta generada: {response[:100]}...")

                    # 3. Detectar idioma
                    language = detect_language(user_text)
                    logger.info(f"🌐 Idioma detectado: {language}")

                    # 4. Generar audio con ElevenLabs (voz según idioma detectado)
                    logger.info(f"🔊 Generando respuesta de voz con ElevenLabs ({language})...")
                    audio_response = await elevenlabs_text_to_speech(response, language)

                    # Fallback a Google TTS si ElevenLabs falla
                    if not audio_response:
                        logger.warning("⚠️ ElevenLabs falló, usando Google TTS como fallback...")
                        audio_response = await google_text_to_speech(response, language)

                    # 5. Enviar audio - OBLIGATORIO para notas de voz
                    if audio_response:
                        success = await send_whatsapp_audio(phone, audio_response)
                        if success:
                            logger.info(f"✅ Respuesta de voz enviada a {phone}")
                        else:
                            logger.warning("⚠️ Falló envío de audio, intentando texto como fallback...")
                            await send_whatsapp_message(phone, response)
                    else:
                        # Fallback final: texto (solo si TODOS los TTS fallan)
                        logger.warning("⚠️ Todos los TTS fallaron, enviando texto")
                        await send_whatsapp_message(phone, response)

                    # 6. Guardar en historial
                    history.append({"role": "user", "content": f"[Nota de voz] {user_text}"})
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

        logger.info(f"💬 Mensaje de {phone}: {user_text[:100]}")

        # Detectar si pide imágenes/info de proyecto específico
        project_request = detect_project_request(user_text)
        if project_request:
            logger.info(f"🏡 Solicitud de proyecto detectada: {project_request}")

        # Obtener historial y generar respuesta
        history = await get_conversation_history(phone)
        response = await chat_completion(user_text, history)

        logger.info(f"Respuesta: {response[:100]}")

        # Enviar respuesta de texto
        await send_whatsapp_message(phone, response)

        # Si pidió info de un proyecto específico, enviar activos visuales
        if project_request and project_request != "general":
            await asyncio.sleep(1)  # Pequeña pausa para que llegue primero el texto
            asset_sent = await send_project_assets(phone, project_request)
            if asset_sent:
                logger.info(f"📸 Activos enviados para proyecto: {project_request}")
        elif project_request == "general":
            # Pidió imagen pero no especificó proyecto
            await asyncio.sleep(0.5)
            await send_whatsapp_message(
                phone,
                "¿De qué proyecto te gustaría ver imágenes? 📸\n\nTenemos proyectos en:\n• Medellín (Crista, Campura)\n• Envigado (Foresta, Polanco)\n• Cartagena (Coralia, Diporto)\n• Bogotá/Sabana (Canarias, Zuá)\n• Cali (Amara)\n\n¿Cuál te interesa?"
            )

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
        "version": "2.1.0",
        "features": ["text", "audio", "vision", "real-estate"],
        "tts": {
            "primary": "elevenlabs",
            "fallback_es": "google-cloud",
            "fallback_en": "groq-playai"
        }
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
