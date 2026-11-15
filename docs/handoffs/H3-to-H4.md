# Handoff H3 → H4

Documento de continuidad para una sesión nueva. Leer en este orden:
`AGENTS.md` → este archivo → `docs/decisions/ADR-007-inference.md` →
`odd/tasks/h3-llm-client.md`.

**Fecha:** 2026-11-15 · **Rama de trabajo:** `feat/h3-llm-client` ·
**Árbol:** limpio · **PRs:** abiertos, **ninguno fusionado**.

> **Advertencia de numeración:** la fase «H3» de este repositorio es el *cliente
> de inferencia* que pidió el usuario, **no** el H3 del plan v0.2 («integración
> agente/MCP»). El plan y el trabajo real divergen. Antes de planificar H4,
> confirmar con el usuario qué hito quiere.

## 1. Estado de las fases

| Fase | Alcance | Estado | PR |
|---|---|---|---|
| H0 | Baseline medido (Fedora 45, Python 3.15.2, sin Pandoc/TeX, Docker+Podman) | cerrado | — |
| H1 | Convertidor determinista `.md/.txt → .tex → .pdf` + branding + sandbox | cerrado, verificado | #1 |
| H2 | Web MVP: auth, subida, trabajos, descargas, UI responsive | cerrado, verificado | #2 (encima de #1) |
| H3 | Cliente de inferencia local + CLI + pantalla experimental | cerrado, verificado | #3 (encima de #2) |

**Orden de fusión:** #1 → #2 → #3. Después de fusionar #1 y #2, #3 se reapunta a
`main` sin conflictos. `#2` aparece como `mergeable=UNKNOWN` solo porque su base
todavía no está fusionada.

Ramas locales: `main`, `feat/h1-converter-cli`, `feat/h2-web-mvp`,
`feat/h3-llm-client`, y `review/security-slice` (inerte, en `d5acca1`, sin
publicar; quedó de una revisión nativa que no se ejecutó).

## 2. Arquitectura

```text
            ┌──────────── navegador (LAN) ────────────┐
            │                                         │
   FastAPI (web/)  ── repositorio SQLite + storage ──┤
        │                                            │
        ├── studio/pipeline  →  security/sandbox ────┤  (PDF en contenedor)
        │        │                                   │
        │        └── branding/ (perfiles + plantilla)│
        │                                            │
        └── ai/client ── provider (urllib) ──────────┘  \  túnel SSH
                                                        > llama.cpp (rose-spark-4b)
```

**Regla de aislamiento:** `studio/` **no** importa `ai/`. Si el modelo se cae, el
convertidor y la web siguen funcionando (probado: PDF generado con
`ROSE_LLM_ENDPOINT` apuntando a un puerto muerto).

**Determinismo:** mismo `.md` ⇒ mismo `.tex` byte a byte. Nada de relojes ni rutas
absolutas dentro del `.tex`; el `manifest.json` sí registra hora, hashes y
runtime.

## 3. Módulos y archivos importantes

```text
backend/rose_nexus/
├── cli.py                  rose convert | brands | doctor | llm
├── core/errors.py          errores con `code` estable y exit_code
├── core/config.py          Settings ROSE_* (motor y sandbox)
├── studio/model.py         AST tipado (bloques e inlines)
├── studio/parser.py        Markdown/TXT → AST; lo no soportado falla con código
├── studio/latex.py         escape carácter por carácter + URLs y assets
├── studio/template.py      render estricto de {{token}}
├── studio/branding.py      perfiles TOML, validación, procedencia
├── studio/pipeline.py      orquestación, assets, manifiesto, PDF opcional
├── security/latex_policy.py  comandos prohibidos, paquetes, rutas
├── security/sandbox.py     argv endurecido del contenedor, timeout, logs acotados
├── storage/artifacts.py    job dir atómico, hashes, manifiesto
├── web/{app,api,ui,html,http_security,bootstrap}.py   FastAPI + UI server-rendered
├── web/{db,models,repository,auth,storage,jobs}.py    datos, sesiones, runner
├── web/llm_screen.py       /app/llm (experimental, autenticada)
├── web/static/app.css      mobile-first, sin assets externos
└── ai/
    ├── settings.py         InferenceSettings.from_env + validación SSRF
    ├── provider.py         LlmProvider + OpenAICompatibleProvider (urllib)
    ├── client.py           semáforo por proceso, métricas, errores tipados
    ├── metrics.py          InferenceMetrics + registro acotado en memoria
    └── errors.py           inference_unavailable/timeout/protocol/http/busy
branding/                   profiles/{invering,demo} · templates · assets con hash
deploy/sandbox/texlive/     Dockerfile de la imagen TeX
deploy/env/inference.sample variables de ejemplo (no hay `.env.example`: bloqueado)
docs/decisions/             ADR-001 … ADR-007
docs/handoffs/              este documento
odd/tasks/                  documentos de feature (specs, tasks, log)
tests/{unit,integration,security,web,ai,fixtures}
scripts/verify.sh           suite reproducible
scripts/build-teximage.sh   build + verificación + digest de la imagen TeX
```

## 4. Modelo local y túnel SSH

| Dato | Valor |
|---|---|
| Motor | llama.cpp, API compatible OpenAI |
| Modelo | `rose-spark-4b` (Qwen3-4B-Instruct-2507 Q4_K_M) |
| Endpoint | `http://127.0.0.1:18080/v1` (por túnel SSH) |
| Contexto / concurrencia | 8192 tokens · **1 slot** · RTX 3060 12 GB |
| Credenciales | ninguna por ahora (`ROSE_LLM_API_KEY` vacío) |

El comando del túnel lo administra el usuario (no está versionado, a propósito).
Patrón: `ssh -N -L 18080:<host-del-modelo>:<puerto> <usuario>@<spark>`.

Verificar antes de cualquier prueba:

```bash
curl -s http://127.0.0.1:18080/v1/models | jq -r '.models[].name'   # rose-spark-4b
```

**El modelo tiene errores factuales conocidos.** Es un borrador, no una fuente de
verdad, y no puede ejecutar nada.

## 5. Comandos para ejecutar y verificar

Pararse siempre en la raíz del repositorio. Python del proyecto:
`.venv/bin/python` (no hace falta activarlo).

```bash
cd /home/marcelomonterrosa/Projects/Rose/rose-nexus
python3 -m venv .venv && .venv/bin/pip install -e '.[web,dev]'   # solo si falta

export PYTHONPATH=backend
export ROSE_SANDBOX_IMAGE="rose-nexus/texlive-sandbox@sha256:df14fa433c90f8ccc1f6f7a4b772bb653edaa7adeb99e1a698ba19cb4434a970"
export ROSE_CONTAINER_RUNTIME=podman

./scripts/verify.sh                          # doctor + suite completa
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m rose_nexus.cli doctor    # ready_to_compile: true
.venv/bin/python -m rose_nexus.cli convert tests/fixtures/markdown/01-headings.md --format pdf --out build/salida

# web
export ROSE_DB_PATH="$PWD/build/runtime/rose-nexus.db"
export ROSE_STORAGE_DIR="$PWD/build/runtime/storage"
.venv/bin/python -m rose_nexus.web --create-user ana
.venv/bin/python -m rose_nexus.web --serve --host 127.0.0.1 --port 8000   # --workers 1

# inferencia
export ROSE_LLM_ENABLED=true
.venv/bin/python -m rose_nexus.cli llm health
.venv/bin/python -m rose_nexus.cli llm ask --prompt "Explicá qué es un sandbox"
.venv/bin/python -m rose_nexus.cli llm bench --runs 3
PYTHONPATH=backend ROSE_LLM_LIVE_TESTS=true .venv/bin/python -m unittest tests.integration.test_llm_live -v

# imagen TeX (solo si hay que reconstruir; cambia el digest)
./scripts/build-teximage.sh
```

Detalle de configuración y errores: `docs/inference.md`.

## 6. Resultados de pruebas y benchmarks

| Área | Pruebas | Estado |
|---|---|---|
| Núcleo de documentos (`tests/unit`, `tests/integration`, `tests/security`) | 160 | OK |
| Web (H2) | 41 | OK |
| Inferencia (H3: `tests/ai`, CLI, pantalla) | 60 | OK |
| **Total** | **260 + 1 skip** | **OK** |

La prueba viva (`tests.integration.test_llm_live`) se saltea salvo
`ROSE_LLM_LIVE_TESTS=true`, para que la suite no dependa del modelo.

Benchmarks medidos (RTX 3060, `rose-spark-4b`):

| Medición | Valor |
|---|---|
| `GET /v1/models` | 215–310 ms |
| Generación | **93,7–95,8 tok/s** (mediana 93,68 con el cliente; 93,76 crudo) |
| Latencia `ask` (~50 tokens de salida) | ~0,99 s |
| PDF | 11 fixtures → 22 páginas; 106–160 KB c/u |

Verificaciones manuales registradas: E2E web H2 **16/16**, E2E pantalla H3
**11/11**, PDF real con el LLM caído, escape de `<script>` aun pidiéndolo al
modelo, y `0` apariciones del prompt en stdout/stderr/métricas.

## 7. Decisiones y ADR

| ADR | Decisión |
|---|---|
| 001 | Baseline medido; sin Pandoc ni TeX en el host |
| 002 | Convertidor propio determinista en vez de Pandoc |
| 003 | Sandbox de contenedor: sin red, rootfs ro, `nobody`, `cap-drop=ALL`, `-no-shell-escape` |
| 004 | `invering` es la identidad canónica (verdes, logo, commit `bd5dd8a`); `demo` provisional rosa/azul |
| 005 | Imagen TeX versionada y fijada por digest; montaje `-v …:ro,Z` por SELinux |
| 006 | FastAPI + SQLite + UI server-rendered (sin SPA); contrato de seguridad web |
| 007 | Inferencia: provider + urllib, loopback + anti-SSRF, sin redirects, un worker, métricas sin contenido |

Invariantes que **no** se renegocian sin ADR nuevo:

1. Sin IA en la conversión de documentos.
2. Todo texto de usuario se escapa; nunca se acepta LaTeX crudo.
3. Compilar fuera del sandbox está prohibido; sin imagen, PDF deshabilitado.
4. Nunca se registran prompts, respuestas ni claves.
5. `studio/` no importa `ai/`.
6. Un worker de uvicorn; el semáforo es por proceso.
7. Las imágenes de contenedor se fijan por digest, nunca por tag.

## 8. Riesgos pendientes y deuda técnica

Ordenados por impacto. Los primeros cuatro son los candidatos naturales a H4.

1. **Ventana de contexto no verificada.** `ROSE_LLM_CONTEXT_TOKENS=8192` es
   declarativo: no hay tokenizador. Un prompt largo se trunca o se rechaza en el
   servidor sin que lo detectemos. La UI corta por caracteres (8000) y el CLI por
   bytes (64 KiB), que no equivalen a tokens.
2. **Sin streaming ni cancelación.** Una generación ocupa el único slot hasta el
   timeout (60 s); la siguiente espera 30 s y recibe `inference_busy`.
3. **Sin grounding ni citas.** El modelo responde de memoria; los errores
   factuales no tienen mitigación más allá del aviso en la UI.
4. **Métricas solo en memoria.** Se pierden al reiniciar; no hay histórico ni
   comparación entre versiones del modelo.
5. **Túnel no supervisado.** `health` es a demanda; si el SSH cae no hay alerta ni
   reintento.
6. **Reproducibilidad parcial de la inferencia.** El modelo aparece en la métrica,
   pero no queda versionado junto a la respuesta.
7. **Deuda heredada de H1/H2:** TLS pendiente para uso en LAN, digest de la imagen
   TeX local (no publicado en un registro), PDF sin `/Title` ni `babel`, fuentes
   Archivo/IBM Plex no empaquetadas (licencias sin verificar).
8. **Cobertura de seguridad del sandbox:** el aislamiento se verificó a nivel de
   argv y con runtime simulado, más una compilación real; **no** hubo auditoría
   adversarial del runtime.
9. **Sin revisión nativa** en H1/H2/H3 por decisión explícita del usuario
   (registrada en `odd/tasks/h1-converter-cli.md`, `L9`). Para revertirla hacen
   falta modelos asignados a `review-risk`, `review-resilience` y
   `review-reliability` en el ruteo; luego revisar por rebanadas de ~400 líneas.

## 9. Alcance inicial recomendado para H4

**Antes de codificar:** confirmar con el usuario qué «H4» quiere, porque la
numeración del plan no coincide con la ejecutada.

Opción A — **Cerrar la deuda de inferencia** (recomendada, 1–2 rebanadas):
1. Presupuesto de contexto real: contar tokens (tokenizador o estimador
   conservador) y fallar con `prompt_too_long` antes de llamar al modelo.
2. Persistir métricas en SQLite con retención explícita, sin contenido.
3. Streaming opcional con cancelación, respetando el slot único.

Opción B — **MCP `rose-documents`** (es el H3 del plan v0.2): servidor STDIO con
`render_document`, `get_document_status`, `list_branding_profiles`, reutilizando
`studio/pipeline` y los contratos de seguridad. Sin exponer HTTP.

Opción C — **Inbox / archivos** (es el H4 del plan): bandeja unificada con subida
móvil y biblioteca. Más grande; conviene después de A.

**No hacer todavía:** agentes autónomos, ejecución de herramientas elegidas por el
modelo, multiagentes, ASR/OCR, o exponer la inferencia fuera de loopback.

## 10. Checklist para la sesión nueva

- [ ] `git status` limpio y rama esperada; PRs #1/#2/#3 siguen abiertos.
- [ ] `./scripts/verify.sh` en verde (260 pruebas, 1 skip).
- [ ] `curl /v1/models` responde si se va a tocar inferencia.
- [ ] Leer `AGENTS.md`, este handoff y el ADR de la fase a tocar.
- [ ] No fusionar, no publicar ni cambiar el digest de la imagen sin autorización.
- [ ] No ejecutar revisiones nativas: están pospuestas por decisión del usuario.
- [ ] Registrar decisiones nuevas como ADR, no como comentarios sueltos.
