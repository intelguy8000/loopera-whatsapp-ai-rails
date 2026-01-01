# Loopera WhatsApp Bot - Railway Edition

Bot de WhatsApp con IA para Loopera, optimizado para Railway.

## Stack

- **Framework**: FastAPI + Uvicorn
- **LLM**: Groq (Llama 3.3 70B)
- **STT**: Groq Whisper (notas de voz)
- **Cache**: Redis (opcional)
- **Deploy**: Railway

## Quick Start

### 1. Deploy en Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/...)

O manual:

```bash
# Conectar repo a Railway
railway link

# Deploy
railway up
```

### 2. Configurar Variables de Entorno

En Railway Dashboard > Variables, agregar:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `VERIFY_TOKEN` | Token para verificar webhook | `loopera-verify-2024` |
| `WHATSAPP_TOKEN` | Token de WhatsApp Cloud API | `EAAG...` |
| `APP_SECRET` | Secret de la app de Meta | `abc123...` |
| `PHONE_NUMBER_ID` | **ID del número** (NO es WABA ID) | `949507764911133` |
| `GROQ_API_KEY` | API Key de Groq | `gsk_...` |
| `REDIS_URL` | URL de Redis (opcional) | Railway lo provee automático |

> **IMPORTANTE**: `PHONE_NUMBER_ID` es el ID del número de teléfono, NO el WABA ID.
> - WABA ID: `1282258597052951` (NO usar para enviar mensajes)
> - Phone Number ID: `949507764911133` (USAR ESTE)

### 3. Obtener Dominio de Railway

1. Ve a Railway Dashboard > tu proyecto
2. Click en el servicio web
3. Settings > Networking > Generate Domain
4. Copia el dominio: `tu-app.up.railway.app`

### 4. Configurar Webhook en Meta Developers

1. Ve a [Meta Developers](https://developers.facebook.com)
2. Tu App > WhatsApp > Configuration
3. Webhook:
   - **Callback URL**: `https://tu-app.up.railway.app/webhook`
   - **Verify Token**: El mismo que pusiste en `VERIFY_TOKEN`
4. Click "Verify and Save"
5. Suscribirse a: `messages`, `message_deliveries`, `message_reads`

---

## CRÍTICO: Shadow Delivery Problem

### El Problema

Desde **Octubre 2025**, Meta tiene un bug donde la suscripción WABA-to-App **no se crea automáticamente** al verificar el webhook.

**Síntomas:**
- Webhook verifica correctamente en Meta ✅
- Health check funciona ✅
- Envías mensaje de WhatsApp... y **nunca llega** ❌
- Los logs de Railway no muestran ningún POST ❌

### La Causa

Meta tiene dos niveles de suscripción:
1. **App Webhook** - Se configura en Meta Developers (esto SÍ funciona)
2. **WABA Subscription** - Conecta tu WABA específico al webhook (esto NO se crea automático)

Sin el paso 2, los mensajes se pierden en el vacío.

### La Solución

**Ejecutar este comando DESPUÉS de verificar el webhook:**

```bash
curl -X POST "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" \
  -d "override_callback_uri=https://TU-APP.up.railway.app/webhook" \
  -d "verify_token=TU_VERIFY_TOKEN"
```

Reemplazar:
- `1282258597052951` → Tu WABA ID
- `TU-APP.up.railway.app` → Tu dominio de Railway
- `$WHATSAPP_TOKEN` → Tu token de WhatsApp
- `TU_VERIFY_TOKEN` → Tu verify token

**Respuesta exitosa:**
```json
{"success": true}
```

### Verificar que la Suscripción Existe

```bash
curl -X GET "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

**Respuesta correcta:**
```json
{
  "data": [
    {
      "whatsapp_business_api_data": {
        "id": "TU_APP_ID",
        "link": "https://tu-app.up.railway.app/webhook",
        "name": "Tu App Name"
      }
    }
  ]
}
```

**Si `data` está vacío** → La suscripción no existe, ejecuta el comando POST.

---

## Troubleshooting

### Webhook no verifica

```
❌ Error: Verification failed
```

**Causas:**
1. `VERIFY_TOKEN` no coincide entre Railway y Meta
2. El endpoint `/webhook` no es accesible
3. Railway aún no terminó el deploy

**Solución:**
```bash
# Probar manualmente
curl "https://tu-app.up.railway.app/webhook?hub.mode=subscribe&hub.verify_token=TU_TOKEN&hub.challenge=test123"

# Debe responder: test123
```

### Mensajes no llegan

```
✅ Webhook verificado
❌ Mensajes no aparecen en logs
```

**99% de las veces**: Falta la suscripción WABA. Ver sección "Shadow Delivery Problem".

**Verificar:**
```bash
# Ver suscripciones actuales
curl -X GET "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

### Bot no responde

```
✅ Webhook recibe mensajes
❌ No envía respuesta
```

**Causas:**
1. `PHONE_NUMBER_ID` incorrecto (¿usaste WABA ID por error?)
2. `WHATSAPP_TOKEN` expirado o inválido
3. `GROQ_API_KEY` no configurado

**Verificar Phone Number ID:**
```bash
# Debe retornar info del número
curl "https://graph.facebook.com/v21.0/949507764911133" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

### Audio no transcribe

```
✅ Mensaje de audio recibido
❌ Error transcribiendo
```

**Causas:**
1. `GROQ_API_KEY` no configurado
2. FFmpeg no instalado (Railway lo incluye por defecto con Nixpacks)

**Verificar Groq:**
```bash
curl "https://api.groq.com/openai/v1/models" \
  -H "Authorization: Bearer $GROQ_API_KEY"
```

### Redis no conecta

```
⚠️ Redis no disponible: Connection refused
```

**No es crítico** - El bot funciona sin Redis, solo pierde el historial de conversación.

**Para agregar Redis:**
1. Railway Dashboard > New Service > Database > Redis
2. La variable `REDIS_URL` se agrega automáticamente

---

## Arquitectura

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   WhatsApp      │────▶│   Railway        │────▶│   Groq      │
│   Cloud API     │◀────│   (FastAPI)      │◀────│   LLM/STT   │
└─────────────────┘     └──────────────────┘     └─────────────┘
                               │
                               ▼
                        ┌─────────────┐
                        │   Redis     │
                        │  (opcional) │
                        └─────────────┘
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Health check (status: online) |
| GET | `/health` | Health check para Railway |
| GET | `/webhook` | Verificación de Meta |
| POST | `/webhook` | Recepción de mensajes |

## IDs del Proyecto

| Tipo | ID | Uso |
|------|----|----|
| WABA ID | `1282258597052951` | Suscripciones, config |
| Phone Number ID | `949507764911133` | Enviar mensajes |

---

## Desarrollo Local

```bash
# Clonar
git clone https://github.com/intelguy8000/loopera-whatsapp-ai-rails
cd loopera-whatsapp-ai-rails

# Crear .env
cp .env.example .env
# Editar .env con tus valores

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar
python main.py

# O con uvicorn
uvicorn main:app --reload --port 8000
```

Para probar localmente con WhatsApp necesitas un túnel (ngrok, cloudflared).

---

## Licencia

Proyecto interno de Loopera.
