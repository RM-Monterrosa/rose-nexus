# Inferencia local (H3/H4)

Cliente desacoplado para el modelo local servido por `llama.cpp`, con medición
exacta del contexto desde H4. **No** ejecuta herramientas, **no** corre agentes
y **no** interviene en la conversión de documentos.

```text
rose llm / pantalla /app/llm
        ↓
InferenceClient  (preflight + presupuesto, concurrencia 1, métricas sin contenido)
        ↓
ContextPreflight  (/props → /apply-template → /tokenize)
        ↓
OpenAICompatibleProvider  (urllib, timeouts, sin redirects)
        ↓
http://127.0.0.1:18080/v1  ← túnel SSH → llama.cpp en Spark (rose-spark-4b)
```

## Requisitos

- Túnel SSH al servidor del modelo escuchando en `127.0.0.1:18080`.
- Python del proyecto: `.venv/bin/python` (no hace falta activar el venv).
- Pararse siempre en la raíz del repositorio.

## Verificar el túnel antes que nada

```bash
curl -s http://127.0.0.1:18080/v1/models | jq -r '.models[].name'
# rose-spark-4b
```

## Variables de entorno

Copia `deploy/env/inference.sample` y exportá lo que necesites. Nada de esto se
commitea con valores reales.

| Variable | Default | Notas |
|---|---|---|
| `ROSE_LLM_ENDPOINT` | `http://127.0.0.1:18080/v1` | Host debe resolver a loopback salvo opt-in |
| `ROSE_LLM_MODEL` | `rose-spark-4b` | Nombre exacto que reporta el servidor |
| `ROSE_LLM_TIMEOUT_SECONDS` | `60` | Timeout de lectura |
| `ROSE_LLM_CONNECT_TIMEOUT_SECONDS` | `5` | Timeout de conexión |
| `ROSE_LLM_MAX_TOKENS` | `512` | Reserva máxima de salida incluida en el presupuesto |
| `ROSE_LLM_TEMPERATURE` | `0.2` | 0–2 |
| `ROSE_LLM_TOP_P` | `0.95` | 0–1 |
| `ROSE_LLM_CONTEXT_TOKENS` | `8192` | Techo aplicado: el contexto efectivo es el mínimo entre este valor y el `n_ctx` del servidor |
| `ROSE_LLM_MAX_CONCURRENCY` | `1` | Semáforo **por proceso** |
| `ROSE_LLM_QUEUE_TIMEOUT_SECONDS` | `30` | Espera máxima antes de `inference_busy` |
| `ROSE_LLM_ENABLED` | `false` | Habilita `ask`/`bench` y la pantalla |
| `ROSE_LLM_ALLOW_REMOTE_ENDPOINT` | `false` | Permite hosts no loopback (no recomendado) |
| `ROSE_LLM_API_KEY` | *(vacío)* | Solo por entorno; nunca en Git ni en logs |

## Presupuesto exacto de contexto (H4)

Cada intento de `llm ask`, cada ejecución de `llm bench` y cada envío web que
llega al cliente hace **tres llamadas loopback adicionales** antes de generar:

1. `GET /props` obtiene `default_generation_settings.n_ctx`.
2. `POST /apply-template` renderiza todos los mensajes con la plantilla real del
   modelo y `add_generation_prompt=true`.
3. `POST /tokenize` cuenta ese prompt con `add_special=false` y
   `parse_special=true`.

El cálculo es:

```text
contexto_efectivo = min(ROSE_LLM_CONTEXT_TOKENS, n_ctx_del_servidor)
tokens_requeridos = rendered_prompt_tokens + max_tokens
```

La medición y el presupuesto se validan **antes** de adquirir el semáforo y
antes de `/chat/completions`. Si `max_tokens` supera por sí solo el contexto
efectivo, la reserva es incompatible y falla con
`inference_configuration_invalid` (exit 2). Si la suma excede el límite, falla
con `prompt_too_long` (exit 2) e informa los conteos. No se invoca la completión
ni se consume el slot en ninguno de esos casos.

No existe fallback heurístico, recorte automático del prompt, resumen del
historial ni reducción silenciosa de `max_tokens`. Si `/props`,
`/apply-template` o `/tokenize` no está disponible, excede un timeout, devuelve
un HTTP no exitoso o una respuesta inválida, la solicitud se rechaza con el
mismo error tipificado del transporte H3. Las tres rutas comparten DNS/SSRF,
bloqueo de redirects, límite de cuerpo de 2 MiB, privacidad y transporte stdlib;
no se agregó ninguna dependencia. `health` solo consulta `/models`: su éxito no
garantiza por sí solo que el servidor implemente las rutas de preflight.

La decisión y su evidencia viva acotada están en
`docs/decisions/ADR-008-context-budget.md`.

## CLI

```bash
cd /home/marcelomonterrosa/Projects/Rose/rose-nexus
export PYTHONPATH=backend
export ROSE_LLM_ENABLED=true

# disponibilidad: no requiere ROSE_LLM_ENABLED
.venv/bin/python -m rose_nexus.cli llm health
.venv/bin/python -m rose_nexus.cli llm health --json

# una consulta; la respuesta va a stdout y las métricas a stderr
.venv/bin/python -m rose_nexus.cli llm ask --prompt "Explicá qué es un sandbox"
.venv/bin/python -m rose_nexus.cli llm ask --prompt-file build/pregunta.txt --max-tokens 256
.venv/bin/python -m rose_nexus.cli llm ask --prompt "hola" --json

# repetir un prompt y comparar con la referencia del servidor
.venv/bin/python -m rose_nexus.cli llm bench --runs 3
.venv/bin/python -m rose_nexus.cli llm bench --runs 5 --json
```

Salida real de referencia (RTX 3060, `rose-spark-4b`, contexto 8192):

```text
available=true model_present=true model=rose-spark-4b latency_ms=214.94
run wall_ms prompt_tokens completion_tokens tok_s finish_reason
1 570.55 26 12 93.68 stop
summary: runs=3 failures=0 wall_median_ms=494.52 tok_s_median=93.68
```

## Pantalla experimental

```bash
export ROSE_LLM_ENABLED=true
.venv/bin/python -m rose_nexus.web --serve --host 127.0.0.1 --port 8000 --workers 1
```

- **http://127.0.0.1:8000/app/llm** (requiere sesión; enlace desde `/app`).
- Sin `ROSE_LLM_ENABLED` la pantalla explica cómo habilitarla y **no llama** al
  modelo.
- Si el modelo está caído, la pantalla lo informa y el resto de la aplicación
  (subidas, trabajos, descargas) sigue funcionando.
- Una respuesta admitida que termina con `finish_reason="length"` muestra
  **Respuesta incompleta**: la generación alcanzó `max_tokens`. Un prompt que no
  cabe en el presupuesto se rechaza antes de generar y muestra `prompt_too_long`.

## Concurrencia: un solo worker

El `BoundedSemaphore` limita **por proceso**. El servidor del modelo tiene **1
slot**, así que:

- Ejecutá uvicorn con **un worker** (`--workers 1`, que es el default).
- Con `--workers N` habría N llamadas simultáneas y `rose-spark-4b` las
  encolaría igual, con latencias impredecibles.
- Si hace falta más capacidad, la solución es un límite compartido entre
  procesos, no subir workers.

## Errores

| Código | Significado | Exit |
|---|---|---|
| `inference_unavailable` | Túnel caído, host inalcanzable o inferencia deshabilitada | 4 |
| `inference_timeout` | Sin respuesta dentro del timeout | 4 |
| `inference_busy` | Cola llena: otra consulta ocupa el único slot | 4 |
| `inference_http_error` | El servidor respondió distinto de 2xx (incluye 3xx: no se siguen) | 5 |
| `inference_protocol_error` | JSON inválido, forma inesperada o cuerpo demasiado grande, también en preflight | 5 |
| `prompt_too_long` | Prompt renderizado + reserva de salida exceden el contexto efectivo; no se genera | 2 |
| `inference_configuration_invalid` | Endpoint/parámetros inválidos, host no loopback o reserva `max_tokens` incompatible con el contexto | 2 |

En la salida humana de `llm ask`, una completión con `finish_reason="length"`
imprime en stderr `warning: generation reached max_tokens; answer may be
incomplete`. La opción `--json` mantiene el contrato `{ok, answer, metrics}` y
expone `finish_reason` en métricas, sin insertar ese aviso textual. El error
`prompt_too_long` usa el mismo canal de errores y exit 2 que otras entradas
inválidas; no cambia la estructura de `Answer`.

## Seguridad y privacidad

- El endpoint debe **resolver a loopback** en el momento de la llamada; un nombre
  que apunte a otra interfaz se rechaza (`inference_endpoint_not_loopback`).
- URLs con `user:pass@host` y esquemas que no sean `http`/`https` se rechazan.
- **No se siguen redirecciones**: un `3xx` es error, no un salto a otro destino.
- Las métricas registran tokens, latencia, tok/s, estado y código de error. Nunca
  el prompt, la respuesta ni la API key. `/props`, `/apply-template` y
  `/tokenize` aplican las mismas reglas de redacción y privacidad que la
  completión; los resultados de preflight conservan solo conteos numéricos.
- El modelo **comete errores factuales**: se usa para redactar borradores, no
  como fuente de verdad ni para decidir acciones.

## Pruebas

```bash
# unitarias + CLI con servidor simulado (sin red al modelo)
PYTHONPATH=backend .venv/bin/python -m unittest tests.ai tests.integration.test_cli_llm -v

# integración viva desactivada por defecto: se saltea sin red al modelo
PYTHONPATH=backend .venv/bin/python -m unittest tests.integration.test_llm_live -v

# una corrida viva acotada y explícita contra llama.cpp (health, ask y concordancia)
PYTHONPATH=backend ROSE_LLM_LIVE_TESTS=true ROSE_LLM_ENABLED=true ROSE_LLM_ENDPOINT=http://127.0.0.1:18080/v1 ROSE_LLM_MODEL=rose-spark-4b .venv/bin/python -m unittest tests.integration.test_llm_live -v

# suite completa
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -t .
```

La prueba viva de concordancia recorre `ContextPreflight` y
`OpenAICompatibleProvider.complete` con `max_tokens=1` y `temperature=0` para
ASCII, historial con marcadores especiales literales y Unicode. Comprueba que
`usage.prompt_tokens` exista y sea exactamente igual al preflight; no fija ni
imprime el contenido generado. Sin `ROSE_LLM_LIVE_TESTS=true` todas las pruebas
de este módulo se saltean, incluso si el endpoint está disponible.

E2E manual recomendado: `llm health` → `llm ask` → `llm bench --runs 3` →
levantar la web y consultar `/app/llm` → bajar el túnel y repetir: todo debe
responder con errores claros y el convertidor debe seguir generando PDF.

## Pendientes (H4)

- Histórico persistente de métricas (hoy el buffer es en memoria).
- Streaming de tokens y cancelación desde la UI.
- Selección de modelo por solicitud y router de capacidades.
- Límite de concurrencia compartido entre procesos.
