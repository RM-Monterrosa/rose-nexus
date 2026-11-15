# Feature: H3 — Cliente de inferencia LLM local

**Estado:** en curso · **Rama:** `feat/h3-llm-client` · **Plan:** `docs/production-plan.md`

## Specs

- **S1** — «Crear un cliente de inferencia desacoplado de la interfaz web,
  preparado para incorporar otros modelos en el futuro.»
- **S2** — «No modificar el convertidor determinista.» El pipeline no importa nada
  del cliente ni del transporte HTTP.
- **S3** — «No implementar todavía MCP ni agentes autónomos.» · «No ejecutar
  herramientas elegidas por el modelo.»
- **S4** — «Respetar el límite de concurrencia de la instancia» (1 slot).
- **S5** — «Manejar la indisponibilidad del modelo sin afectar el convertidor ni el
  resto de la aplicación.»
- **S6** — «No registrar prompts completos ni información privada.» Métricas:
  tokens, latencia y velocidad; nunca contenido.
- **S7** — «No incluir credenciales en Git.» · «No exponer la API de inferencia
  públicamente.» Endpoint por defecto en loopback; remoto exige opt-in explícito.
- **S8** — «Registrar métricas de inferencia: tokens, latencia y velocidad.»
- **S9** — «Crear un comando CLI para probar el modelo desde Fedora.»
- **S10** — «Implementar pruebas automatizadas con respuestas simuladas y pruebas
  de integración opcionales.»
- **S11** — «Si integrarla en la interfaz web es viable sin ampliar excesivamente
  H3, hacerlo mediante una pantalla experimental protegida por autenticación.»
- **S12** — «No modificar el contenido original de los documentos.»
- **S13** — «PR independiente hacia `main`» · «No fusiones el PR sin mi
  autorización.»
- **S14** — «No instalar dependencias globales.» Transporte con `urllib` (stdlib).
- **S15** — «Concurrencia: utilizar inicialmente un solo worker de Uvicorn.
  Documentar que `BoundedSemaphore` limita por proceso.»
- **S16** — «FastAPI: ejecutar las llamadas bloqueantes de `urllib` fuera del event
  loop.»
- **S17** — «Seguridad: bloquear redirecciones HTTP no autorizadas y validar los
  destinos para evitar SSRF.»
- **S18** — «Compatibilidad: manejar correctamente proveedores que no devuelvan
  `usage` o `timings`.»

## Infraestructura verificada (2026-11-15)

| Dato | Valor medido |
|---|---|
| Endpoint por túnel SSH | `http://127.0.0.1:18080/v1` |
| `GET /v1/models` | 200 en 0,27 s; modelo `rose-spark-4b`, `capabilities: ["completion"]` |
| `POST /v1/chat/completions` | 200 en 0,26 s; `usage {prompt_tokens:22, completion_tokens:2}`, `timings.predicted_per_second: 71.4` |
| Campos reales | raíz: `choices, created, id, model, object, system_fingerprint, timings, usage` |
| Límite declarado | contexto 8192, 1 slot, RTX 3060 12 GB |

El modelo tiene **errores factuales conocidos**: se usa para redactar y responder,
nunca para decidir acciones ni ejecutar herramientas.

## Decisión de alcance

- Núcleo (`backend/rose_nexus/ai/`) sin dependencias, con transporte `urllib`.
- Interfaz `LlmProvider` + implementación `OpenAICompatibleProvider`; otros
  proveedores se agregan sin tocar el cliente ni la web.
- CLI bajo `rose llm …`; pantalla experimental en `/app/llm`, autenticada y CSRF,
  apagada por defecto (`ROSE_LLM_ENABLED`).
- **El PR #3 queda encadenado** sobre `feat/h2-web-mvp` porque `main` aún no tiene
  backend: PR #1 y #2 siguen abiertos. Tras fusionarlos, el destino natural es
  `main`.

## Tasks

| ID | Spec | Entrega |
|---|---|---|
| T1 | S1, S5, S7, S14 | `ai/`: errores tipados, configuración por entorno, provider compatible OpenAI |
| T2 | S6, S8 | Métricas sin contenido (tokens, latencia, tok/s) + registro acotado |
| T3 | S4 | Cliente con semáforo de concurrencia y errores de saturación |
| T4 | S9 | CLI `rose llm health|ask|bench` |
| T5 | S10 | Pruebas con servidor HTTP simulado + integración opcional contra el túnel |
| T6 | S11 | Pantalla experimental `/app/llm` autenticada; llamadas por `run_in_threadpool` (S16) |
| T7 | S13 | ADR-007, documentación E2E y PR #3 |
| T8 | S2, S12 | Regresión: el convertidor y los documentos originales no cambian |
| T9 | S15 | Servidor con un worker; límite de concurrencia documentado como por-proceso |
| T10 | S17 | Anti-SSRF: resolución a loopback + sin redirecciones |
| T11 | S18 | Métricas tolerantes a `usage`/`timings` ausentes |

## Log

- **L1** — Solicitud de H3 (mensaje del usuario que abre la fase). Sus
  restricciones literales están citadas en S1–S14.
- **L2** — Túnel SSH al modelo verificado antes de programar: `/v1/models` y
  `/v1/chat/completions` responden 200. La forma real de la respuesta incluye
  `usage` y `timings`, así que las métricas salen de datos medidos y no de
  estimaciones.
- **L3** — `?` `.env.example` sigue bloqueado por la política de rutas del
  harness; las variables se documentan en `docs/inference.md` y en un archivo de
  ejemplo con otro nombre.
- **L4** — Plan aprobado con cuatro condiciones adicionales (S15–S18): un worker
  de uvicorn, `urllib` fuera del event loop, anti-SSRF con bloqueo de
  redirecciones y tolerancia a respuestas sin `usage`/`timings`. Se incorporan al
  núcleo antes de cerrarlo.
