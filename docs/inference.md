# Inferencia local (H3)

Cliente desacoplado para el modelo local servido por `llama.cpp`. **No** ejecuta
herramientas, **no** corre agentes y **no** interviene en la conversión de
documentos.

```text
rose llm / pantalla /app/llm
        ↓
InferenceClient  (concurrencia 1, métricas sin contenido)
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
| `ROSE_LLM_MAX_TOKENS` | `512` | Techo de salida |
| `ROSE_LLM_TEMPERATURE` | `0.2` | 0–2 |
| `ROSE_LLM_TOP_P` | `0.95` | 0–1 |
| `ROSE_LLM_CONTEXT_TOKENS` | `8192` | Declarativo: la ventana del servidor |
| `ROSE_LLM_MAX_CONCURRENCY` | `1` | Semáforo **por proceso** |
| `ROSE_LLM_QUEUE_TIMEOUT_SECONDS` | `30` | Espera máxima antes de `inference_busy` |
| `ROSE_LLM_ENABLED` | `false` | Habilita `ask`/`bench` y la pantalla |
| `ROSE_LLM_ALLOW_REMOTE_ENDPOINT` | `false` | Permite hosts no loopback (no recomendado) |
| `ROSE_LLM_API_KEY` | *(vacío)* | Solo por entorno; nunca en Git ni en logs |

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
| `inference_protocol_error` | JSON inválido, forma inesperada o cuerpo demasiado grande | 5 |
| `inference_configuration_invalid` | Endpoint/parámetros inválidos o host no loopback | 2 |

## Seguridad y privacidad

- El endpoint debe **resolver a loopback** en el momento de la llamada; un nombre
  que apunte a otra interfaz se rechaza (`inference_endpoint_not_loopback`).
- URLs con `user:pass@host` y esquemas que no sean `http`/`https` se rechazan.
- **No se siguen redirecciones**: un `3xx` es error, no un salto a otro destino.
- Las métricas registran tokens, latencia, tok/s, estado y código de error. Nunca
  el prompt, la respuesta ni la API key.
- El modelo **comete errores factuales**: se usa para redactar borradores, no
  como fuente de verdad ni para decidir acciones.

## Pruebas

```bash
# unitarias + CLI con servidor simulado (sin red al modelo)
PYTHONPATH=backend .venv/bin/python -m unittest tests.ai tests.integration.test_cli_llm -v

# integración opcional: se saltea sola si el túnel no responde
PYTHONPATH=backend ROSE_LLM_ENABLED=true .venv/bin/python -m unittest tests.integration.test_llm_live -v

# suite completa
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -t .
```

E2E manual recomendado: `llm health` → `llm ask` → `llm bench --runs 3` →
levantar la web y consultar `/app/llm` → bajar el túnel y repetir: todo debe
responder con errores claros y el convertidor debe seguir generando PDF.

## Pendientes (H4)

- Histórico persistente de métricas (hoy el buffer es en memoria).
- Streaming de tokens y cancelación desde la UI.
- Selección de modelo por solicitud y router de capacidades.
- Límite de concurrencia compartido entre procesos.
