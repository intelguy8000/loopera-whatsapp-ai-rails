# Troubleshooting - Loopera WhatsApp AI Bot

Guia detallada de errores comunes y sus soluciones.

## 1. Shadow Delivery Problem (CRITICO)

### Sintoma
- Webhook verifica correctamente (GET /webhook retorna 200)
- Pero los mensajes de WhatsApp nunca llegan al servidor
- No hay logs de POST /webhook

### Causa
Desde Octubre 2025, Meta cambio el comportamiento:
- Antes: La suscripcion WABA-to-App se creaba automaticamente
- Ahora: Debes crear la suscripcion manualmente con POST

### Solucion

```bash
# Crear suscripcion WABA-to-App
curl -X POST "https://graph.facebook.com/v21.0/{WABA_ID}/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" \
  -d "override_callback_uri=https://tu-app.railway.app/webhook" \
  -d "verify_token=tu_verify_token"
```

### Verificar suscripcion

```bash
curl "https://graph.facebook.com/v21.0/{WABA_ID}/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

Respuesta esperada:
```json
{
  "data": [
    {
      "whatsapp_business_api_data": {
        "id": "tu-app-id",
        "link": "https://tu-app.railway.app/webhook"
      }
    }
  ]
}
```

### Notas importantes
- `WABA_ID` es diferente a `PHONE_NUMBER_ID`
- WABA ID: Se usa para suscripciones
- Phone Number ID: Se usa para enviar mensajes

---

## 2. $PORT no se expande en Docker

### Sintoma
```
Invalid value for '--port': '$PORT' is not a valid integer
```

### Causa
Railway inyecta la variable `PORT` en runtime, pero Docker no expande variables
de entorno en la directiva `CMD` cuando se usa forma exec `["cmd", "arg"]`.

### Intentos fallidos

```dockerfile
# NO FUNCIONA - forma exec
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "$PORT"]

# NO FUNCIONA - forma shell
CMD uvicorn main:app --host 0.0.0.0 --port $PORT

# NO FUNCIONA - con /bin/sh
CMD ["/bin/sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
```

### Solucion

Leer el puerto en Python:

```python
# main.py
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
```

```dockerfile
# Dockerfile
CMD ["python", "main.py"]
```

---

## 3. Token de WhatsApp expira cada 24 horas

### Sintoma
```
{"error": {"message": "Session has expired", "code": 190}}
```

### Causa
Los tokens temporales de Meta (generados desde el panel de pruebas) expiran en 24h.

### Solucion

Crear un System User con token permanente:

1. Ir a [Meta Business Settings](https://business.facebook.com/settings/)
2. System Users > Add
3. Nombre: `whatsapp-bot-production`
4. Rol: Admin
5. Add Assets:
   - Apps > Tu App > Full Control
   - WhatsApp Accounts > Tu WABA > Full Control
6. Generate New Token:
   - App: Tu App
   - Token Expiration: Never
   - Permissions:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
7. Guardar el token generado

### Verificar token

```bash
curl "https://graph.facebook.com/v21.0/me?access_token=$WHATSAPP_TOKEN"
```

---

## 4. PlayAI TTS requiere aceptar terminos

### Sintoma
```
{"error": {"message": "The model 'playai-tts' requires terms acceptance"}}
```

### Causa
Groq requiere que aceptes los terminos de uso de PlayAI antes de usar el modelo.

### Solucion

1. Ir a [Groq Playground](https://console.groq.com/playground?model=playai-tts)
2. Leer y aceptar los terminos de PlayAI
3. Intentar de nuevo

---

## 5. WhatsApp no acepta audio WAV

### Sintoma
```
{"error": {"message": "Param file must be a file with one of the following types: audio/aac, audio/mp4, audio/mpeg, audio/amr, audio/ogg"}}
```

### Causa
PlayAI TTS genera audio en formato WAV, pero WhatsApp no lo acepta.

### Solucion

Convertir WAV a MP3 con ffmpeg:

```python
import subprocess
import tempfile

def convert_wav_to_mp3(wav_data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wav_file:
        wav_file.write(wav_data)
        wav_path = wav_file.name

    mp3_path = wav_path.replace('.wav', '.mp3')

    subprocess.run([
        'ffmpeg', '-i', wav_path,
        '-acodec', 'libmp3lame', '-y', mp3_path
    ], capture_output=True)

    with open(mp3_path, 'rb') as mp3_file:
        return mp3_file.read()
```

### Formatos aceptados por WhatsApp
- audio/aac
- audio/mp4
- audio/mpeg (MP3)
- audio/amr
- audio/ogg (con codec opus)

---

## 6. ffmpeg no encontrado en container

### Sintoma
```
FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'
```

### Causa
La imagen base de Python no incluye ffmpeg.

### Solucion con Dockerfile

```dockerfile
FROM python:3.11-slim

# Instalar ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "main.py"]
```

### Solucion con Nixpacks (alternativa)

Crear `nixpacks.toml`:
```toml
[phases.setup]
nixPkgs = ["ffmpeg"]
```

**Nota:** Nixpacks puede causar otros problemas, Dockerfile es mas confiable.

---

## 7. "Object does not exist" al enviar mensajes

### Sintoma
```
{"error": {"message": "(#100) Object with ID 'XXXXX' does not exist"}}
```

### Causa
Estas usando el WABA ID en lugar del Phone Number ID para enviar mensajes.

### Solucion

Usar el Phone Number ID correcto:

```python
# INCORRECTO - esto es el WABA ID
PHONE_NUMBER_ID = "1282258597052951"

# CORRECTO - este es el Phone Number ID
PHONE_NUMBER_ID = "949507764911133"
```

### Como encontrar el Phone Number ID

1. Meta Business Suite > WhatsApp Manager
2. Phone Numbers
3. Copiar el ID que aparece (no el numero de telefono)

---

## 8. Google TTS no genera audio

### Sintoma
```
Google TTS client not configured
```

### Causa
La variable `GOOGLE_APPLICATION_CREDENTIALS_JSON` no esta configurada o es invalida.

### Solucion

1. Crear Service Account en Google Cloud Console
2. Generar JSON key
3. Minificar el JSON (una sola linea)
4. Pegar en Railway:

```
GOOGLE_APPLICATION_CREDENTIALS_JSON={"type":"service_account","project_id":"mi-proyecto","private_key_id":"abc123","private_key":"-----BEGIN PRIVATE KEY-----\nMIIE...","client_email":"tts@mi-proyecto.iam.gserviceaccount.com",...}
```

### Verificar permisos
El Service Account necesita el rol `Cloud Text-to-Speech API User` o `Owner`.

---

## 9. Redis connection refused

### Sintoma
```
redis.exceptions.ConnectionError: Error connecting to localhost:6379
```

### Causa
Redis no esta configurado o la URL es incorrecta.

### Solucion en Railway

1. Agregar Redis addon al proyecto
2. Railway automaticamente inyecta `REDIS_URL`
3. Verificar en Settings > Variables que existe

### El bot funciona sin Redis
Si Redis no esta disponible, el bot funciona pero sin memoria conversacional.

---

## 10. Webhook verification failed

### Sintoma
- Meta muestra "Webhook verification failed"
- HTTP 403 en logs

### Causa
El `VERIFY_TOKEN` no coincide con el configurado en Meta.

### Solucion

1. Verificar que `VERIFY_TOKEN` en Railway coincide con Meta
2. Asegurarse que el endpoint es exactamente `/webhook`
3. Verificar que el servidor esta corriendo

### Test manual

```bash
curl "https://tu-app.railway.app/webhook?hub.mode=subscribe&hub.verify_token=tu-token&hub.challenge=test123"
```

Respuesta esperada: `test123`

---

## 11. Rate limit exceeded (Groq)

### Sintoma
```
{"error": {"message": "Rate limit exceeded"}}
```

### Causa
Has superado los limites del free tier de Groq.

### Limites Free Tier

| Modelo | RPM | TPD |
|--------|-----|-----|
| Llama 3.3 70B | 30 | 100K |
| Whisper Turbo | 20 | 2,000 |
| PlayAI TTS | 20 | - |

### Solucion

1. Implementar rate limiting en el codigo
2. Agregar delays entre requests
3. Upgrade a plan de pago de Groq

---

## 12. Audio transcription fails

### Sintoma
```
[Error transcribiendo audio]
```

### Posibles causas

1. **Formato incorrecto:** WhatsApp envia OGG, Whisper prefiere MP3
2. **Audio muy largo:** Limite de 25MB
3. **Audio corrupto:** Error en descarga

### Solucion

Convertir OGG a MP3 antes de transcribir:

```python
subprocess.run([
    "ffmpeg", "-i", "input.ogg",
    "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1",
    "output.mp3", "-y"
], capture_output=True)
```

---

## Contacto

Si encuentras un error no documentado aqui, abre un issue en GitHub.
