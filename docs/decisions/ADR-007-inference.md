# ADR-007 — Arquitectura de inferencia local (H3)

- **Estado:** aceptado
- **Fecha:** 2026-11-15
- **Contexto:** existe un `llama.cpp` remoto con `rose-spark-4b`
  (Qwen3-4B-Instruct-2507 Q4_K_M, contexto 8192, 1 slot, RTX 3060 12 GB),
  accesible solo por túnel SSH en `http://127.0.0.1:18080/v1`. La API es
  compatible con OpenAI y ya respondió `/v1/models` y `/v1/chat/completions`.
  El modelo **comete errores factuales**: no es autoridad ni ejecutor.

## Decisiones

### 1. Interfaz de proveedor, no SDK

`LlmProvider` (Protocol) con `health()` y `complete()`;
`OpenAICompatibleProvider` sobre `urllib.request`. Sin SDK de OpenAI, sin
`requests`, sin dependencias nuevas: el motor y el cliente comparten la misma
regla de biblioteca estándar. Otro modelo se agrega implementando la interfaz.

### 2. Endpoint en loopback y defensa SSRF

- Host permitido por defecto: `127.0.0.1`, `localhost`, `::1`. Un host remoto
  exige `ROSE_LLM_ALLOW_REMOTE_ENDPOINT=true`.
- **Resolución en tiempo de llamada:** `socket.getaddrinfo` y exigir que *todas*
  las direcciones resueltas sean loopback. Un nombre que apunta a otra interfaz
  se rechaza (`inference_endpoint_not_loopback`). Esto evita el SSRF por DNS que
  el chequeo de cadena no detecta.
- Se rechazan URLs con credenciales embebidas (`user:pass@host`) y esquemas
  distintos de `http`/`https`.
- **Redirecciones bloqueadas:** `urllib` las sigue por defecto; se instala un
  `HTTPRedirectHandler` que no redirige. Cualquier `3xx` es `InferenceHTTPError`.
  Sin esto, un 302 convertiría el cliente en un proxy hacia un destino arbitrario.

### 3. Concurrencia: un worker, semáforo por proceso

`BoundedSemaphore(max_concurrency)` con `max_concurrency=1` y timeout de cola.
**El límite es por proceso:** con `uvicorn --workers N` habría N llamadas
simultáneas contra un servidor de 1 slot. Por eso el despliegue de H3 usa
**un solo worker** (`--workers 1`, el valor por defecto de uvicorn) y está
documentado en `docs/inference.md`. Si en el futuro se necesita más capacidad, la
solución es un límite compartido (archivo/cola/servicio), no subir workers.

### 4. Bloqueo fuera del event loop

El transporte es sincrónico. En FastAPI la llamada se ejecuta con
`starlette.concurrency.run_in_threadpool`, de modo que un modelo lento no
congela el resto de la aplicación (subidas, trabajos, descargas). El CLI es
sincrónico por definición.

### 5. Timeouts y sin reintentos automáticos

Timeout de conexión y de lectura separados. **Sin reintentos automáticos:** con
un solo slot, reintentar multiplica la latencia y puede encadenar saturación. El
usuario ve el error tipado y decide.

### 6. Métricas sin contenido

Una métrica por llamada: `request_id`, modelo, `prompt_tokens`,
`completion_tokens`, `total_tokens`, latencia, tokens/s, `finish_reason`, estado,
código de error, host del endpoint y hora UTC. **Nunca** prompt, respuesta ni
`api_key`. Los campos pueden ser `None` si el proveedor no devuelve `usage` o
`timings`: se registra `null`, no un cero inventado.

El registro es un buffer acotado en memoria. H3 no persiste métricas; si se
quiere histórico, va a SQLite en H4 con retención explícita.

### 7. Aislamiento de fallos

`backend/rose_nexus/ai/` es una hoja del grafo: `studio/` no la importa. Si el
modelo está caído, el convertidor, la API de documentos y la web siguen
funcionando; solo la pantalla experimental informa el error. Una prueba lo
verifica con el cliente forzado a fallar.

### 8. Sin herramientas, sin agentes, sin MCP

El modelo devuelve texto. No se ejecutan herramientas elegidas por el modelo, no
hay function calling, no hay bucles autónomos. La pantalla experimental está
marcada como tal y advierte que las respuestas pueden ser incorrectas.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| SDK de OpenAI | Dependencia nueva para un `POST` de 60 líneas |
| `requests` | Ídem; `urllib` cubre el caso con timeouts explícitos |
| Streaming (SSE) | Útil, pero agrega protocolo y pruebas; se evalúa en H4 |
| Reintentos con backoff | Amplifican la saturación de un único slot |
| Ejecutar tool calls | Fuera de alcance y peligroso con un modelo que yerra |

## Riesgos aceptados en H3

- **Errores factuales del modelo:** se muestra como borrador, no como verdad.
- **Un solo slot:** una consulta lenta bloquea a la siguiente hasta el timeout de
  cola (30 s por defecto) y luego responde `inference_busy`.
- **Dependencia del túnel SSH:** si se cae, `health` lo dice y nada más se rompe.
- **Contexto 8192:** entradas largas deben truncarse o rechazarse en la capa que
  llama; H3 no envía documentos completos.
- **Métricas en memoria:** se pierden al reiniciar el proceso.
