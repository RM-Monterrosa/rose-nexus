# Runbook — Rose Documents en Pi

Guía para la prueba local de H3 con Pi 1.5.2. Esta integración es STDIO local; no abre HTTP ni conecta un LLM. La configuración del repositorio está en `.pi/mcp.json` y permanece `enabled: false` hasta que la persona la active.

## Límites antes de habilitar

- Revisa `AGENTS.md`, ADR-009 y las dos Skills bajo `.agents/skills/`. Pi pide confianza de proyecto para cargar `.pi/mcp.json` y `.agents/skills`; solo confía después de inspeccionar esos archivos. La confianza de Pi **no** es sandbox ni autorización de datos.
- `ROSE_MCP_USERNAME` fija la cuenta web a la que quedan ligados los cuatro handlers. Configúralo en el entorno de Pi; no es un argumento de herramienta.
- El worker y la cola de `JobRunner` son por proceso. **Detén el servidor web/uvicorn y confirma que no haya un job activo antes de iniciar MCP.** MCP recupera jobs `running` como interrumpidos y ejecuta su propio worker. No ejecutes simultáneamente la web y este servidor contra la misma base.
- La imagen PDF debe estar disponible como `repo@sha256:<64 hex>`. Sin ella, PDF queda deshabilitado y no hay compilación en el host.

## Preparación

Desde la raíz del repositorio, con el `.venv` local ya creado:

```bash
export PATH="$PWD/.venv/bin:$PATH"
export ROSE_MCP_USERNAME='nombre-de-la-cuenta-web'
export ROSE_MCP_WORKER_MODE=serialized
# Deben ser los mismos valores que usa la instalación web, si no se usan los defaults.
export ROSE_DB_PATH="$PWD/build/runtime/rose-nexus.db"
export ROSE_STORAGE_DIR="$PWD/build/runtime/storage"
export ROSE_BRANDING_DIR="$PWD/branding"
export ROSE_OUTPUT_DIR="$PWD/build/runtime/output"
```

Ajusta DB y storage a la ubicación real de la aplicación web; **no** inicialices una base nueva para acceder a documentos existentes. La cuenta y el documento fuente deben existir en Rose Nexus. El proceso comprueba la base, el storage y el usuario configurado y falla cerrado si faltan.

`ROSE_MCP_WORKER_MODE=serialized` es una confirmación operativa, no un mutex entre procesos. La garantía inicial sigue siendo apagar la web mientras se usa el MCP.

## Prueba aislada reproducible

Con Pi 1.5.2 en `PATH`, ejecuta desde el repo:

```bash
PATH="$PWD/.venv/bin:$PATH" PYTHONPATH=backend python scripts/verify-mcp-pi.py
```

El script crea una base, cuenta, fuente y configuración de Pi temporales; aísla la carpeta de configuración mediante `PI_CODING_AGENT_DIR`, deshabilita actividad de red de Pi y elimina los temporales al terminar. No lee la base real, no requiere un modelo ni Docker y prueba el render `.tex` sin PDF. Comprueba `pi mcp list --json` y mide, en una muestra, tiempos/bytes de inicialización, `tools/list`, ping y los cuatro workflows frente a funciones directas. Las diferencias son observaciones locales, **no** una mejora garantizada ni una medida de tokens/s o VRAM.

### Evidencia de una ejecución local (una muestra)

| Medición | Directa | MCP roundtrip | Diferencia observada |
|---|---:|---:|---:|
| Listar perfiles | 2.021 ms | 2.017 ms | -0.004 ms |
| Metadatos | 0.074 ms | 0.153 ms | +0.080 ms |
| Encolar render `.tex` | 0.629 ms | 0.591 ms | -0.039 ms |
| Estado final | 0.296 ms | 0.535 ms | +0.239 ms |

Pi 1.5.2 descubrió 4 herramientas en exposición `direct` (367.149 ms de descubrimiento). `initialize` fue 58.937 ms; baseline `ping`, 0.059 ms. El render terminó `completed` con dos artefactos TeX-only. La variación de una muestra es ruido esperable; **no** demuestra una mejora de rendimiento. El script también registra tamaños de frames/respuestas sin imprimir IDs ni contenido documental.

## Activación opt-in

1. Deja detenido el worker web y exporta las variables de arriba en el mismo entorno desde el que arrancará Pi.
2. Desde la raíz, inicia `pi` y acepta confianza de proyecto solo después de revisar las Skills y `.pi/mcp.json`.
3. En `/mcp`, habilita `rose-documents`. La config queda `direct` para las cuatro herramientas; no hay herramientas destructivas. Comprueba que el estado sea conectado y que aparezcan `render_document`, `get_document_status`, `list_branding_profiles` y `get_document_metadata`.
4. Para una prueba fuera de una sesión TUI, `pi mcp list --json` comprueba servidores habilitados. **No lo ejecutes mientras una sesión Pi ya tenga iniciado este MCP**, porque eso iniciaría otro worker sobre la misma base.
5. Cuando cierres Pi, espera el cierre del servidor MCP antes de volver a iniciar la web.

La prueba real con el usuario puede usar `document-authoring`: primero confirma `source_id`, preset y formato; después de la autorización explícita, encola una sola renderización y consulta el `job_id`. El estado MCP no incluye bytes ni URLs autenticadas: descarga desde la UI Rose Nexus. La persona debe inspeccionar visualmente el PDF; el agente no puede declarar esa inspección hecha solo porque el job terminó.

## Diagnóstico

- `ROSE_MCP_WORKER_MODE` ausente: exporta exactamente `serialized`; no significa que sea seguro dejar la web encendida.
- Usuario, base o storage no encontrados: verifica que las rutas sean las mismas de la aplicación web y que el usuario local exista.
- Pi no conecta: ejecuta `pi mcp --help`, revisa `/mcp` y `pi mcp list --json` **con la web detenida**. STDOUT está reservado a JSON-RPC; diagnósticos aparecen en STDERR.
- `sandbox_unavailable`: no intentes compilar en el host; configura la imagen TeX fijada por digest.
- `rate_limited`: espera antes de volver a llamar. Render tiene un límite adicional de 3 solicitudes/minuto; no reintentes automáticamente.
