# ADR-009 — Rose Documents MCP STDIO y Pi

- **Estado:** aceptado para la integración local supervisada
- **Fecha:** 2026-11-15
- **Alcance:** H3, servidor `rose-documents` sobre el servicio documental compartido

## Contexto

Rose Nexus ya tiene servicios web que validan perfiles, crean jobs y aplican ownership por usuario. Pi necesita una interfaz local interoperable sin duplicar el convertidor, abrir HTTP ni permitir que el modelo elija identidades o rutas. La prueba inicial usa Pi 1.5.2 y el protocolo MCP 2025-11-25.

`JobRunner` y su cola son proceso-locales. Un segundo worker sobre la misma base no es seguro: su recuperación puede marcar jobs `running` como interrumpidos y las colas no se comparten entre procesos.

## Decisiones

1. El servidor es STDIO, JSON-RPC por líneas y biblioteca estándar. No se añade el paquete `mcp`, un endpoint HTTP ni una integración SDK de Pi.
2. El dispatcher publica exactamente cuatro herramientas directas: `render_document`, `get_document_status`, `list_branding_profiles` y `get_document_metadata`. No expone herramientas destructivas.
3. Los handlers capturan un `User` local seleccionado por `ROSE_MCP_USERNAME` al iniciar el proceso. Ningún esquema acepta `user_id`, principal, filesystem path o URL. El servicio compartido vuelve a comprobar ownership en cada lectura y render.
4. El inicio exige `ROSE_MCP_WORKER_MODE=serialized`. Antes de iniciar MCP, la persona debe detener el worker web; MCP inicia su propio worker y solo comparte SQLite/almacenamiento. No se afirma compatibilidad concurrente web+MCP.
5. El archivo de proyecto `.pi/mcp.json` declara el servidor con exposición `direct`, pero `enabled: false`. Se habilita explícitamente desde Pi después de revisar el proyecto, configurar la identidad y detener el worker web. La confianza de proyecto de Pi no sustituye aislamiento, ownership ni sandbox.
6. `render_document` solo encola un job. La persona solicita y confirma fuente, preset y formato; Pi no ejecuta ciclos de generación ni reintentos autónomos. El límite general es 60 llamadas/minuto y render tiene un límite adicional de 3/minuto por proceso.
7. Status y metadatos son compactos: no contienen bytes fuente, rutas, ni URLs autenticadas. Los detalles de excepciones internas se sustituyen por un mensaje genérico y los demás mensajes de error se limitan a 2000 caracteres. La descarga se hace por la UI web autenticada. PDF solo se compila con la imagen TeX fijada por digest y el sandbox existente; no hay fallback al host.
8. STDERR registra únicamente nombre de herramienta, resultado y código de error estable. No registra argumentos, documentos, prompts, respuestas, secretos ni IDs. Las mediciones opt-in informan tiempos y tamaños observados; no afirman mejoras de tokens/s o VRAM.
9. Las Skills `document-authoring` y `safe-workflow` son instrucciones lazy revisadas, no una frontera de permisos.

## Consecuencias

- Pi puede descubrir las cuatro herramientas en modo `direct`; el modelo no recibe una identidad ni una ruta para seleccionar.
- La operación inicial se limita a un proceso MCP serializado. Un worker compartido o ejecución simultánea requiere un diseño posterior con ownership/coordination atómicos y nuevas pruebas de alta consecuencia.
- El script opt-in `scripts/verify-mcp-pi.py` crea una base y archivos desechables, comprueba la conexión real desde `pi mcp list` y mide workflows TeX-only. No requiere un modelo ni Docker y no certifica el flujo PDF de otra instalación.
- La inspección visual del PDF y su descarga permanecen bajo control de la persona en la UI autenticada.
