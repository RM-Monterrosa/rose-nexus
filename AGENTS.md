# AGENTS.md — Rose Nexus

Reglas vinculantes para cualquier agente (Pi, subagente o persona) que trabaje en
este repositorio. Si una instrucción de este archivo choca con una petición del
usuario, se detiene el trabajo y se pregunta.

## 1. Estado del proyecto y prioridad para sesiones nuevas

**Leer esta sección antes de explorar o cambiar código.** La fuente del roadmap de
producto es `docs/production-plan.md`; el estado implementado se determina con el
Git y el código actuales. `docs/Rose_Nexus_Contexto_de_Traspaso_v1.2_CORREGIDO.md`
es un resumen histórico útil, no una certificación del estado remoto. Antes de
continuar, revisar `git status --short --branch` y respetar todo cambio existente.

### Roadmap oficial: hitos completos, en curso y pendientes

Los nombres oficiales son **H0, H1–H8 y H7b**. No confundirlos con los nombres
históricos de entregas técnicas T-LLM/T-CTX usados en ramas.

- **H0 — Discovery / baseline: PARCIAL.** Se reportaron la instancia RTX 3060 de
  12 GB, llama.cpp, Qwen3-4B y una conexión por túnel SSH. No dar por verificados
  todos los criterios de H0: benchmark 8B, persistencia y otros datos de entorno
  siguen pendientes de confirmación.
- **H1 — Conversor CLI: COMPLETO, según implementación y verificaciones
  reportadas.** Convierte Markdown/TXT a LaTeX determinista; usa el perfil
  canónico `invering` y mantiene `demo` como provisional. La compilación PDF es
  opcional y solo ocurre en la imagen TeX aislada fijada por digest. Se reportaron
  11 fixtures, 22 páginas PDF y 160 pruebas iniciales.
- **H2 — Aplicación web MVP: COMPLETO según reporte; validación móvil LAN/TLS
  pendiente.** FastAPI sirve una UI responsive renderizada en servidor, con
  autenticación, SQLite, cargas, trabajos y descargas. No es una SPA separada.
  Se reportó E2E 16/16; no asumir que acceso móvil por LAN con TLS ya está
  verificado.
- **H3 — Integración agente/MCP del roadmap: EN CURSO.** `rose-documents` se
  implementó localmente por STDIO reutilizando servicios web existentes. T1
  (servicio compartido) está en `db807c8`; T2a/T2b/T3/T4 están implementados y
  verificados en el árbol local. Suite completa: 318 OK, 1 skip; Pi 1.5.2
  descubrió las cuatro herramientas `direct` en un store temporal. La config de
  proyecto permanece opt-in/disabled. El worker sigue siendo proceso-local: la
  prueba exige serializarlo y detener el worker web. El usuario confirmó que
  terminó la validación de la rama `demo` y autorizó crear el PR; el target
  observado sigue en `9b3e51d`, ancestro de la rama de feature. El PR #10 está
  abierto contra `demo`; T5 aún requiere revisión independiente y cierre. **No afirmar que H3
  está cerrado ni que la Pi cotidiana del usuario quedó configurada.** Consultar
  `odd/tasks/rose-documents-mcp.md` y revisar `git status --short --branch` antes
  de continuar; la nota de estado remoto puede cambiar.
- **H4 — Inbox y archivos: PENDIENTE.** La biblioteca/carga básica de H2 no
  completa el Inbox universal ni el uso entre dos dispositivos autorizados.
- **H5 — Learn: PRIORIDAD ACORDADA. H6 — Dev: DESPUÉS.** El usuario confirmó
  Learn primero y Dev después; ambos hitos siguen pendientes. No ampliar su
  alcance ni crear hitos nuevos. La infraestructura documental y las referencias
  se reutilizan entre ambos.
- **H7 — Productividad LAN avanzada: PENDIENTE. H7b — App móvil con inferencia
  nativa: PENDIENTE. H8 — Endurecimiento y release: PENDIENTE.**

### Entregas técnicas completadas que no cambian la numeración del roadmap

- **T-LLM (llamada “H3” en el repo): COMPLETA según reporte.** Cliente
  OpenAI-compatible con `urllib`, CLI `rose llm`, pantalla experimental
  deshabilitada por defecto, endpoint local, métricas sin contenido y concurrencia
  limitada a un slot. No es el MCP H3 del roadmap ni un agente autónomo.
- **T-CTX (llamada “H4” en el repo): COMPLETA según reporte.** `ContextPreflight`
  mide el prompt con `/props`, `/apply-template` y `/tokenize`, aplica un
  presupuesto fail-closed y no trunca ni reduce silenciosamente `max_tokens`.
  Se reportaron 277 pruebas OK, 1 skip y seis comparaciones sintéticas con delta
  cero; esa evidencia no garantiza otros modelos o versiones del servidor.

`README.md` refleja ahora el estado local de H3; el handoff
`docs/handoffs/H3-to-H4.md` sigue siendo histórico frente al task MCP y al Git
actual. Las ramas locales no prueban el estado de PR remotos. No fusionar ni
publicar sin autorización.

Fuera de alcance por decisión explícita del usuario:

- Usar IA (LLM) para convertir, resumir o reescribir documentos.
- Aceptar LaTeX crudo de una fuente no confiable.
- Inventar identidad visual corporativa.

## 2. Reglas no negociables

1. **Determinismo.** La misma entrada debe producir el mismo `.tex` byte a byte.
   Sin relojes, números aleatorios, rutas absolutas ni orden de `dict` inestable
   dentro de la salida generada.
2. **Sin IA en la conversión.** El pipeline es código convencional.
3. **Escape estricto.** Todo texto de usuario se escapa para LaTeX. Nunca se
   interpola contenido sin escapar en la plantilla.
4. **Sandbox real o nada.** La compilación de documentos no confiables corre en
   un contenedor con red deshabilitada, rootfs de solo lectura, usuario no root,
   `--cap-drop=ALL`, `no-new-privileges` y límites de CPU/RAM/PIDs/tiempo. Si no
   hay runtime o imagen, el flujo PDF queda **deshabilitado**; no se simula
   aislamiento ni se compila en el host.
5. **Imagen fijada por digest.** Solo se acepta `repo@sha256:<64 hex>`; las tags
   mutables se rechazan.
6. **Sin `shell-escape`.** `-no-shell-escape` siempre; además se valida el `.tex`
   contra una política de construcciones prohibidas antes de compilar.
7. **Sin instalaciones globales.** Dependencias Python solo en `.venv` local.
   Nada de `sudo`, `dnf install`, `npm -g` ni similar sin autorización explícita.
8. **Sin borrados sin autorización.** No `rm -rf`, `git clean`, `git reset --hard`
   ni sobrescritura de archivos del usuario sin permiso explícito.
9. **Scripts remotos: primero inspección.** No ejecutar `curl | bash`, instaladores
   ni scripts descargados sin leerlos y explicar qué hacen.
10. **Secretos fuera del repo.** Nada de claves en código, tests, fixtures o logs.
11. **Simetría de dependencias.** Este incremento usa solo la biblioteca estándar
    de Python. Si se propone una dependencia nueva, se justifica en un ADR.

## 3. Estructura

```text
backend/rose_nexus/    core · studio · security · storage · web (FastAPI + UI) ·
                       ai (cliente de inferencia) · mcp (STDIO en desarrollo) ·
                       cli.py
branding/              perfiles versionados, plantillas y assets con hash
deploy/                Dockerfile de la imagen TeX y variables de ejemplo
docs/                  plan, arquitectura, amenazas, ADRs, inferencia y handoffs
odd/tasks/             documentos de feature de Organic Driven Development
tests/                 unit, integration, security, web, ai y fixtures
scripts/               verificación reproducible y build de la imagen TeX
```

Continuidad entre sesiones: primero leer este estado, luego
`odd/tasks/rose-documents-mcp.md` hasta `## Log`, y después consultar
`docs/production-plan.md` para alcance oficial. Usar
`docs/Rose_Nexus_Contexto_de_Traspaso_v1.2_CORREGIDO.md` como antecedente
histórico. `docs/handoffs/H3-to-H4.md` describe una etapa anterior; no sustituye
el estado actual de Git. Revisar siempre la rama y los cambios locales antes de
reanudar.

## 4. Comandos canónicos

```bash
# Verificación completa usando el entorno del proyecto (incluye dependencias web)
PATH="$PWD/.venv/bin:$PATH" ./scripts/verify.sh

# Suite directa
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -t . -v

# CLIs
PYTHONPATH=backend python3 -m rose_nexus.cli doctor
PYTHONPATH=backend python3 -m rose_nexus.cli brands
PYTHONPATH=backend python3 -m rose_nexus.cli convert tests/fixtures/markdown/01-headings.md --brand demo --out build
```

## 5. Pruebas

- **Test-first.** Primero la prueba que falla (RED), después la implementación
  (GREEN). Se registra la evidencia en el reporte del incremento.
- Runner canónico: `unittest` de la biblioteca estándar. Las pruebas también son
  compatibles con `pytest` si está disponible.
- Cada prueba verifica la interfaz pública: código de salida, `stdout`, `stderr`
  y, cuando aplique, que la entrada rechazada no deje artefactos escritos.
- Los fixtures son datos versionados; no se generan al vuelo salvo la imagen
  mínima ya incluida.
- Nada de pruebas que dependan de red, de Docker funcionando o de la hora del
  sistema; el sandbox se prueba con un runtime simulado (stub) en `PATH`.
- Todo test nuevo debe fallar si se rompe la regla que cubre.

## 6. Branding

- **Fuente verificada:** `https://forgejo.invering.com/INVERING/BRANDING.git`,
  rama `main`, commit `bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2`, sistema
  `4.1-logo-greens`. Detalle y procedencia en
  `docs/decisions/ADR-004-branding-source.md`.
- **Tokens reales:** Bosque Digital `#05130F`, Verde Profundo `#006838`, Verde
  Medio `#60A83D`, Verde Hoja `#73B43E`, Verde Luz `#8DC63F`, Hueso `#F2F5EF`.
  Tipografía declarada: Archivo/Archivo Expanded, IBM Plex Sans, IBM Plex Mono.
- **Restricción del lock:** `BRAND-LOCK.md` prohíbe acentos cálidos como colores
  de marca y desaconseja la estética «SaaS azul». Consecuencia: **rosa + azul
  nunca se aplica a marca INVERING**; ese par solo puede vivir en el perfil
  provisional `demo`.
- **Identidad canónica (decidida por el usuario el 2026-11-15): `invering`.**
  Es el perfil predeterminado de la CLI y de la API: verdes verificados del repo
  de branding, logo oficial y commit de origen fijado. `demo` (rosa + azul) sigue
  existiendo como perfil **provisional** y solo se usa con `--brand demo`; nunca
  representa a INVERING.
- Dirección de producto registrada: la idea de «rosa y azul» para Rose Nexus
  quedó como experimento provisional, no como identidad de los documentos
  corporativos. Si se retoma, requiere un ADR nuevo.
- Perfiles: `invering` (no provisional; exige `source` con commit exacto) y
  `demo` (provisional). **Prohibido inventar** logos, paletas o tipografías
  fuera de lo declarado en esos perfiles.
- Los activos copiados desde el repo de branding registran SHA-256 y commit de
  origen. Los SVG se descartan (requieren `shell-escape`); se usan PNG.
- Las fuentes **no** se empaquetan hasta verificar su licencia, que el repo de
  origen no declara.
- **Nunca ejecutar** scripts del repositorio de branding (`scripts/validate_brand.py`
  incluido): se inspeccionan como texto.

## 7. Código

- Python 3.11+ con anotaciones de tipo y docstrings en módulos y funciones públicas.
- Sin estado global mutable; funciones puras donde sea posible.
- Errores con código estable (`invalid_input`, `latex_policy_violation`,
  `sandbox_unavailable`, `compile_failed`) y mensaje comprensible para la persona.
- Idioma: código, identificadores, comentarios y mensajes técnicos en **inglés**;
  documentación de proyecto y mensajes al usuario final en **español**.
- Commits por unidad de trabajo revisable, en rama de feature, con Conventional
  Commits.

## 8. Límites conocidos de este incremento

- Subset de Markdown documentado en `docs/architecture.md`; lo no soportado
  falla con error de validación, no se ignora en silencio.
- **PDF habilitado solo con la imagen TeX fijada por digest** (ADR-005). Sin
  `ROSE_SANDBOX_IMAGE` válida, `--format pdf` falla con exit 4 y no escribe
  artefactos. La imagen se construye con `./scripts/build-teximage.sh`.
- En Fedora con SELinux `Enforcing` el montaje usa `-v …:ro,Z`; con
  `--mount type=bind` el contenedor no puede leer `/src` (ver ADR-003).
- Los PDF no llevan `/Title` en metadatos; `babel` (partición española) e índice
  siguen pendientes.
- Las fuentes Archivo/IBM Plex no se empaquetan: licencias sin verificar.

## 9. Inferencia local y MCP supervisado

- El modelo es **borrador, no verdad**: tiene errores factuales conocidos. Nunca
  se usa como fuente de verdad ni para decidir acciones.
- El modelo **no elige ni ejecuta herramientas de forma autónoma** y no inicia
  bucles de agentes. El H3 oficial del roadmap incorpora un servidor MCP STDIO
  supervisado e invocado explícitamente por Pi/persona; MCP no convierte el modelo
  en autoridad ni permite saltarse validaciones, permisos o sandbox.
- **Nunca** registrar prompts, respuestas ni `ROSE_LLM_API_KEY`. Solo métricas:
  tokens, latencia, tok/s, estado y código de error.
- Endpoint **solo loopback**; se valida la resolución DNS en tiempo de llamada y
  **no se siguen redirecciones**. Habilitar un endpoint remoto exige ADR.
- Todo intento de generación pasa por `ContextPreflight` y las rutas exactas
  `/props` + `/apply-template` + `/tokenize`, con transporte stdlib y las mismas
  políticas SSRF/DNS, redirects, timeouts, límite de cuerpo y privacidad de H3.
  No se agregan dependencias ni fallbacks heurísticos.
- `ROSE_LLM_CONTEXT_TOKENS` es un techo aplicado:
  `contexto_efectivo=min(configuración, n_ctx)` y
  `requerido=rendered_prompt_tokens+max_tokens`. El exceso o una reserva de
  generación incompatible se rechaza **antes** del semáforo/completión, sin
  truncar prompts ni reducir `max_tokens` silenciosamente.
- Un worker de uvicorn: el semáforo de concurrencia es **por proceso** y la
  instancia tiene **1 slot**.
- `studio/` no importa `ai/`: si el modelo se cae, el convertidor y la web siguen
  funcionando.
- Los avisos humanos de CLI/web por `finish_reason="length"` advierten posible
  truncamiento sin cambiar los contratos JSON ni `Answer`. La evidencia viva de
  concordancia es opt-in y numérica; no fija ni registra salidas del modelo.
