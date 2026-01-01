# Experimento: Railway para WhatsApp Bots

## Resumen Ejecutivo

| Campo | Valor |
|-------|-------|
| **Objetivo** | Validar si Railway funciona correctamente para WhatsApp bots |
| **Fecha Inicio** | 1 Enero 2026 |
| **Fecha Fin** | 1 Enero 2026 |
| **Resultado** | ✅ EXITOSO |
| **URL Produccion** | https://web-production-5ad96.up.railway.app |

**Conclusion Principal:** Railway funciona perfectamente para WhatsApp bots. Los problemas anteriores eran de configuracion de Meta, no de infraestructura.

---

## Timeline del Experimento

### Fase 1: Preparacion (30 min)

1. **Analisis del bot existente en Render**
   - Clonado repo: `github.com/intelguy8000/loopera-whatsapp-bot`
   - Documentada estructura: main.py, services/, config
   - Identificados componentes: FastAPI, Groq, Redis, WhatsApp Cloud API

2. **Creacion de nuevo repo para Railway**
   - Repo: `github.com/intelguy8000/loopera-whatsapp-ai-rails`
   - Estructura simplificada (single file main.py)
   - Configuracion especifica para Railway (railway.json)

### Fase 2: Desarrollo (45 min)

1. **Creacion de main.py**
   - FastAPI con endpoints: `/`, `/health`, `/webhook`
   - Integracion Groq (LLM + Whisper)
   - Redis opcional para historial
   - Background tasks para respuesta rapida a Meta

2. **Configuracion de deploy**
   - Procfile: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
   - railway.json: healthcheckPath configurado
   - Variables de entorno documentadas

### Fase 3: Deploy en Railway (15 min)

1. **Creacion de proyecto en Railway**
   - Conectado repo de GitHub
   - Build automatico con Nixpacks
   - Dominio generado: `web-production-5ad96.up.railway.app`

2. **Configuracion de variables**
   - VERIFY_TOKEN
   - WHATSAPP_TOKEN
   - PHONE_NUMBER_ID (949507764911133)
   - GROQ_API_KEY

### Fase 4: Configuracion de Meta (20 min)

1. **Webhook en Meta Developers**
   - Callback URL configurada
   - Verificacion exitosa al primer intento

2. **Suscripcion WABA (Shadow Delivery Fix)**
   - Ejecutado POST a /subscribed_apps
   - Confirmada suscripcion activa

### Fase 5: Pruebas (15 min)

1. **Health checks**
   - GET / : ✅ `{"status": "online"}`
   - GET /health : ✅ `{"status": "healthy"}`

2. **Webhook verification**
   - GET /webhook con challenge : ✅ Retorna challenge

3. **Mensajes de texto**
   - Enviado mensaje desde WhatsApp : ✅ Recibido en logs
   - Bot responde correctamente : ✅

4. **Notas de voz**
   - Enviado audio desde WhatsApp : ✅ Recibido
   - Transcripcion con Whisper : ✅ Funciona
   - Respuesta del bot : ✅

---

## Pasos Ejecutados

### 1. Clonar y analizar bot de Render

```bash
git clone https://github.com/intelguy8000/loopera-whatsapp-bot /tmp/render-bot
```

Estructura encontrada:
- `app/main.py` - FastAPI app
- `app/services/groq_service.py` - LLM + Whisper
- `app/services/redis_service.py` - Session management
- `app/services/whatsapp_service.py` - WhatsApp Cloud API

### 2. Crear nuevo repo para Railway

```bash
git clone https://github.com/intelguy8000/loopera-whatsapp-ai-rails
cd loopera-whatsapp-ai-rails
```

Archivos creados:
- `main.py` (single file, 415 lineas)
- `Procfile`
- `requirements.txt`
- `railway.json`
- `.env.example`
- `README.md`

### 3. Deploy en Railway

1. Railway Dashboard > New Project > Deploy from GitHub
2. Seleccionar repo `loopera-whatsapp-ai-rails`
3. Configurar variables de entorno
4. Generate Domain

### 4. Configurar Meta

1. Meta Developers > WhatsApp > Configuration
2. Webhook URL: `https://web-production-5ad96.up.railway.app/webhook`
3. Verify Token: `loopera-verify-2024`
4. Suscribir campos: `messages`

### 5. Ejecutar Shadow Delivery Fix

```bash
curl -X POST "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN" \
  -d "override_callback_uri=https://web-production-5ad96.up.railway.app/webhook" \
  -d "verify_token=loopera-verify-2024"
```

Respuesta: `{"success": true}`

### 6. Verificar suscripcion

```bash
curl "https://graph.facebook.com/v21.0/1282258597052951/subscribed_apps" \
  -H "Authorization: Bearer $WHATSAPP_TOKEN"
```

Respuesta confirmo app suscrita correctamente.

---

## Evidencia

### Screenshots disponibles

1. **Railway Dashboard** - Deploy exitoso con health check verde
2. **Meta Developers** - Webhook verificado
3. **Railway Logs** - Mensajes POST /webhook recibidos
4. **WhatsApp** - Conversacion con bot funcionando

### Logs de Railway

```
2026-01-01 10:15:23 INFO Iniciando Loopera WhatsApp Bot...
2026-01-01 10:15:23 INFO Phone Number ID: 949507764911133
2026-01-01 10:15:23 INFO Groq configurado: Si
2026-01-01 10:15:45 INFO POST /webhook recibido
2026-01-01 10:15:45 INFO Mensaje de 521234567890 - Tipo: text
2026-01-01 10:15:46 INFO Respuesta: Hola! Soy el asistente virtual de Loopera...
2026-01-01 10:15:46 INFO Mensaje enviado a 521234567890
```

---

## Conclusiones Tecnicas

### 1. Railway SI funciona para WhatsApp bots

- **Health checks**: Funcionan correctamente con `/health`
- **Puerto dinamico**: `$PORT` se inyecta correctamente
- **Logs en tiempo real**: Mejor que Render
- **Build con Nixpacks**: FFmpeg incluido por defecto (necesario para audio)

### 2. El problema nunca fue Railway

El problema original era:
- **Falta de suscripcion WABA**: Meta no crea automaticamente la suscripcion del WABA al App
- **Shadow Delivery Problem**: Webhook verifica pero mensajes no llegan

### 3. Comparativa final

| Aspecto | Railway | Render | Ganador |
|---------|---------|--------|---------|
| Deploy speed | ~2 min | ~3 min | Railway |
| Logs | Tiempo real, detallados | Basicos | Railway |
| Health checks | Nativo | Nativo | Empate |
| Redis | Addon integrado | Externo | Railway |
| Precio | $5/mes | $7/mes | Railway |
| Cold starts | Por validar | Estable | Render? |
| Documentacion | Buena | Buena | Empate |

---

## Recomendaciones para Futuros Deployments

### Checklist obligatorio

1. **Antes de deploy**
   - [ ] Verificar PHONE_NUMBER_ID (NO usar WABA ID)
   - [ ] Tener GROQ_API_KEY listo
   - [ ] Tener WHATSAPP_TOKEN valido

2. **Durante deploy**
   - [ ] Configurar todas las variables de entorno
   - [ ] Generar dominio publico
   - [ ] Verificar health check: `curl https://tu-app/health`

3. **Despues de deploy**
   - [ ] Configurar webhook en Meta Developers
   - [ ] **CRITICO**: Ejecutar POST a /subscribed_apps
   - [ ] Verificar suscripcion con GET a /subscribed_apps
   - [ ] Enviar mensaje de prueba

### Errores comunes a evitar

1. **Usar WABA ID en lugar de Phone Number ID**
   - WABA ID: Para suscripciones y config
   - Phone Number ID: Para enviar mensajes

2. **Olvidar el Shadow Delivery Fix**
   - Siempre ejecutar POST a /subscribed_apps
   - Verificar que la respuesta sea `{"success": true}`

3. **No verificar logs**
   - Si no hay POST en logs, el problema es Meta (suscripcion)
   - Si hay POST pero no respuesta, el problema es el bot (codigo/config)

---

## Archivos del Experimento

| Archivo | Descripcion |
|---------|-------------|
| `main.py` | FastAPI app completa (415 lineas) |
| `Procfile` | Comando de inicio para Railway |
| `railway.json` | Configuracion de deploy |
| `requirements.txt` | Dependencias Python |
| `.env.example` | Template de variables |
| `README.md` | Documentacion completa |
| `EXPERIMENT-RESULTS.md` | Este archivo |

---

## Proximos Pasos

1. **Monitorear cold starts** - Validar comportamiento despues de inactividad
2. **Agregar Redis** - Para persistencia de conversaciones
3. **Migrar bot principal** - Si cold starts son aceptables
4. **Documentar para equipo** - Crear guia de deployment estandar

---

*Experimento realizado por: Equipo Loopera*
*Fecha: 1 Enero 2026*
