# Contexto de continuación — H3 MCP / PR a `demo`

## Estado al pausar

- Rama local/remota: `feat/rose-documents-protocol`, HEAD `019b0e8` (`feat(mcp): add supervised rose-documents stdio server`). Commit publicado en `origin/feat/rose-documents-protocol`.
- PR #10 está **abierto** contra `demo`: https://github.com/RM-Monterrosa/rose-nexus/pull/10. No se hizo merge.
- La regresión de seguridad de esta sesión evita que `get_document_status` revele detalles crudos de excepciones `internal_error` que podrían incluir rutas; limita los demás mensajes a 2000 caracteres.
- `docs/Rose_Nexus_Contexto_de_Traspaso_v1.2_CORREGIDO.md` ya aparecía como untracked al inicio; se preservó sin editar y se excluyó del commit/PR.
- El usuario confirmó que el otro agente terminó la validación de `demo`. La revisión independiente final de T5 aún está pendiente.

## Implementación local

- **T2a/T2b:** `mcp/stdio.py` aporta framing UTF-8 newline-delimited y límites; `mcp/server.py` lo integra con lifecycle, initialize, ping, list/call, errores JSON-RPC y errores tipados.
- **T3:** `mcp/tools.py` publica cuatro herramientas con principal `User` capturado fuera de los argumentos, ownership vía `document_service`, validación cerrada, 60 llamadas/minuto general y render 3/minuto, errores con códigos estables y trazas sin argumentos/contenido.
- **T4:** `mcp/runtime.py` + `python -m rose_nexus.mcp` selecciona `ROSE_MCP_USERNAME`, verifica DB/storage existentes y exige `ROSE_MCP_WORKER_MODE=serialized`. No ejecutar simultáneamente con el worker web: la cola es proceso-local y el arranque recupera jobs `running`.
- `.pi/mcp.json` declara las cuatro herramientas `direct`, pero `enabled:false` por defecto; `.agents/skills/` contiene `document-authoring` y `safe-workflow`; ADR-009 y el runbook están escritos.
- `README.md`, `AGENTS.md` y `odd/tasks/rose-documents-mcp.md` se actualizaron. T2a–T4 aparecen completados; T5 sigue abierto hasta revisión independiente y cierre.

## Evidencia local

- `PATH="$PWD/.venv/bin:$PATH" ./scripts/verify.sh`: **318 tests OK, 1 skip** (incluye la nueva regresión de filtrado de errores internos).
- Suite MCP enfocada: **34 tests OK**.
- `pi --version`: 1.5.2; `pi mcp --help` confirmado.
- `scripts/verify-mcp-pi.py` pasó con base/storage temporales, red de Pi deshabilitada y sin modelo: Pi 1.5.2 conectó con exposición `direct`, descubrió cuatro herramientas y terminó una renderización `.tex` con dos artefactos. Última muestra: discovery 363.894 ms; `initialize` 58.251 ms; `tools/list` 0.111 ms; ping 0.384 ms; perfiles directo/MCP 1.865/2.025 ms; metadata 0.062/0.148 ms; enqueue 0.632/0.565 ms; status 0.294/0.562 ms. Es una muestra local, no benchmark ni afirmación de mejora de modelo o VRAM.
- No se comprobó el TUI `/mcp` manual, la configuración persistente de la Pi del usuario, compilación PDF ni ejecución web+MCP concurrente. El script comprueba la conexión real de Pi CLI usando una carpeta de configuración global temporal.
- El usuario confirmó que la otra persona terminó la validación de `demo`. `git fetch origin demo` confirmó el target `9b3e51d`, ancestro de esta rama. `gh pr create` abrió el PR #10 contra `demo`; el cuerpo final fue revisado y corregido. No se hizo merge.
- Un intento de `pi --approve mcp list --json` falló porque esa combinación de opciones no está admitida; no repetir ni describirlo como fallo del servidor. El comando verificado es `pi mcp list --json` dentro del script aislado.
- `git diff --check` pasó; `rg` no encontró whitespace final en los archivos cambiados.

## Continuación obligatoria

1. Al abrir la siguiente sesión, seguir `AGENTS.md`: revisar `git status --short --branch`, leer `odd/tasks/rose-documents-mcp.md` hasta `## Log` y consultar `docs/production-plan.md` antes de tocar código.
2. Revisar todas las diferencias, incluyendo archivos untracked; no resetear/limpiar ni sobrescribir nada. Ejecutar suite y prueba Pi después de cualquier cambio.
3. Consultar el estado y los comentarios del PR #10; no fusionarlo sin autorización explícita.
4. Completar T5: obtener revisión independiente, resolver observaciones con tests y actualizar `odd/tasks/rose-documents-mcp.md` y `AGENTS.md` al cerrar H3. La config MCP cotidiana sigue sin habilitarse y no se afirma que el usuario ya la tenga.
5. Tras cerrar H3, seguir la prioridad de `AGENTS.md`/roadmap: H4 Inbox y archivos está pendiente; luego H5 Learn (prioridad acordada) antes de H6 Dev. No saltar hitos ni ampliar alcance.
