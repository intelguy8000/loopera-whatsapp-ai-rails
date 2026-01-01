# Loopera WhatsApp Bot - Railway Edition

Bot de WhatsApp con IA para Loopera, optimizado para Railway.

---

## Resultados del Experimento

| Campo | Valor |
|-------|-------|
| **Fecha** | 1 Enero 2026 |
| **Estado** | ✅ EXITOSO |
| **URL Produccion** | https://web-production-5ad96.up.railway.app |

### Conclusion

**Railway funciona correctamente para WhatsApp bots.** El problema anterior era configuracion de Meta (webhook + suscripciones WABA), NO infraestructura de Railway.

### Comparativa Railway vs Render

| Aspecto | Railway | Render |
|---------|---------|--------|
| Deploy | ✅ Funciona | ✅ Funciona |
| Health checks | ✅ /health | ✅ /health |
| Puerto dinamico | $PORT | $PORT |
| Cold starts | Por validar | Estable |
| Logs | Tiempo real | Basicos |
| Redis addon | Integrado | Externo |
| Precio base | $5/mes | $7/mes |

### Checklist de Deployment Verificado

- [x] Health check respondiendo
- [x] Webhook verificacion paso
- [x] Mensajes llegando al bot
- [x] Bot respondiendo correctamente
- [x] Transcripcion de audio funcionando
- [x] Redis conectado (opcional)

### Lecciones Aprendidas

1. **Railway NO tiene problemas de infraestructura** para este caso de uso
2. **La clave es configurar correctamente Meta** (webhook + suscripciones)
3. **El Shadow Delivery Problem sigue siendo el error #1** a verificar cuando los mensajes no llegan
4. **Siempre ejecutar el POST a /subscribed_apps** despues de verificar el webhook

---

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

| Variable | Descripcion | Ejemplo |
|----------|-------------|---------|
| `VERIFY_TOKEN` | Token para verificar webhook | `loopera-verify-2024` |
| `WHATSAPP_TOKEN` | Token de WhatsApp Cloud API | `EAAG...` |
| `APP_SECRET` | Secret de la app de Meta | `abc123...` |
| `PHONE_NUMBER_ID` | **ID del numero** (NO es WABA ID) | `949507764911133` |
| `GROQ_API_KEY` | API Key de Groq | `gsk_...` |
| `REDIS_URL` | URL de Redis (opcional) | Railway lo provee automatico |

> **IMPORTANTE**: `PHONE_NUMBER_ID` es el ID del numero de telefono, NO el WABA ID.
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

## CRITICO: Shadow Delivery Problem

### El Problema

Desde **Octubre 2025**, Meta tiene un bug donde la suscripcion WABA-to-App **no se crea automaticamente** al verificar el webhook.

**Sintomas:**
- Webhook verifica correctamente en Meta ✅
- Health check funciona ✅
- Envias mensaje de WhatsApp... y **nunca llega** ❌
- Los logs de Railway no muestran ningun POST ❌

### La Causa

Meta tiene dos niveles de suscripcion:
1. **App Webhook** - Se configura en Meta Developers (esto SI funciona)
2. **WABA Subscription** - Conecta tu WABA especifico al webhook (esto NO se crea automatico)

Sin el paso 2, los mensajes se pierden en el vacio.

### La Solucion

**Ejecutar este comando DESPUES de verificar el webhook:**

```bash
curl -X POST "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" \
  -d "override_callback_uri=https://TU-APP.up.railway.app/webhook" \
  -d "verify_token=TU_VERIFY_TOKEN"
```

Reemplazar:
- `1282258597052951` -> Tu WABA ID
- `TU-APP.up.railway.app` -> Tu dominio de Railway
- `$WHATSAPP_TOKEN` -> Tu token de WhatsApp
- `TU_VERIFY_TOKEN` -> Tu verify token

**Respuesta exitosa:**
```json
{"success": true}
```

### Verificar que la Suscripcion Existe

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

**Si `data` esta vacio** -> La suscripcion no existe, ejecuta el comando POST.

---

## Troubleshooting

### Webhook no verifica

```
❌ Error: Verification failed
```

**Causas:**
1. `VERIFY_TOKEN` no coincide entre Railway y Meta
2. El endpoint `/webhook` no es accesible
3. Railway aun no termino el deploy

**Solucion:**
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

**99% de las veces**: Falta la suscripcion WABA. Ver seccion "Shadow Delivery Problem".

**Verificar:**
```bash
# Ver suscripciones actuales
curl -X GET "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

### Bot no responde

```
✅ Webhook recibe mensajes
❌ No envia respuesta
```

**Causas:**
1. `PHONE_NUMBER_ID` incorrecto (usaste WABA ID por error?)
2. `WHATSAPP_TOKEN` expirado o invalido
3. `GROQ_API_KEY` no configurado

**Verificar Phone Number ID:**
```bash
# Debe retornar info del numero
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

**No es critico** - El bot funciona sin Redis, solo pierde el historial de conversacion.

**Para agregar Redis:**
1. Railway Dashboard > New Service > Database > Redis
2. La variable `REDIS_URL` se agrega automaticamente

---

## Arquitectura

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   WhatsApp      │────>│   Railway        │────>│   Groq      │
│   Cloud API     │<────│   (FastAPI)      │<────│   LLM/STT   │
└─────────────────┘     └──────────────────┘     └─────────────┘
                               │
                               v
                        ┌─────────────┐
                        │   Redis     │
                        │  (opcional) │
                        └─────────────┘
```

## Endpoints

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/` | Health check (status: online) |
| GET | `/health` | Health check para Railway |
| GET | `/webhook` | Verificacion de Meta |
| POST | `/webhook` | Recepcion de mensajes |

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

Para probar localmente con WhatsApp necesitas un tunel (ngrok, cloudflared).

---

## Licencia

Proyecto interno de Loopera.
