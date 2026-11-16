# Contexto de continuación — H3 MCP / PR a `demo`

## Estado al pausar

- Rama local: `feat/rose-documents-protocol`, HEAD `9558644`.
- Los cambios de H3 están **sin stage y sin commit**. No se hizo push, fetch, merge ni PR.
- En la continuación se añadió una regresión de seguridad: el estado MCP ya no devuelve detalles crudos de excepciones con `internal_error`, que podían incluir rutas del host; los demás mensajes persistidos quedan limitados a 2000 caracteres. Ese cambio también sigue sin commit.
- `docs/Rose_Nexus_Contexto_de_Traspaso_v1.2_CORREGIDO.md` ya aparecía como untracked al inicio de esta sesión: preservarlo y no editarlo ni borrarlo.
- El usuario autorizó: terminar/verificar y crear un PR dirigido a la nueva rama remota `demo`; **no autorizó hacer merge**. Otro agente está comprobando `demo`. Confirmar que terminó y que la rama funciona antes de publicar.

## Implementación local

- **T2a/T2b:** `mcp/stdio.py` aporta framing UTF-8 newline-delimited y límites; `mcp/server.py` lo integra con lifecycle, initialize, ping, list/call, errores JSON-RPC y errores tipados.
- **T3:** `mcp/tools.py` publica cuatro herramientas con principal `User` capturado fuera de los argumentos, ownership vía `document_service`, validación cerrada, 60 llamadas/minuto general y render 3/minuto, errores con códigos estables y trazas sin argumentos/contenido.
- **T4:** `mcp/runtime.py` + `python -m rose_nexus.mcp` selecciona `ROSE_MCP_USERNAME`, verifica DB/storage existentes y exige `ROSE_MCP_WORKER_MODE=serialized`. No ejecutar simultáneamente con el worker web: la cola es proceso-local y el arranque recupera jobs `running`.
- `.pi/mcp.json` declara las cuatro herramientas `direct`, pero `enabled:false` por defecto; `.agents/skills/` contiene `document-authoring` y `safe-workflow`; ADR-009 y el runbook están escritos.
- `README.md`, `AGENTS.md` y `odd/tasks/rose-documents-mcp.md` se actualizaron. T2a–T4 aparecen completados; T5 sigue pendiente.

## Evidencia local

- `PATH="$PWD/.venv/bin:$PATH" ./scripts/verify.sh`: **318 tests OK, 1 skip** (incluye la nueva regresión de filtrado de errores internos).
- Suite MCP enfocada: **34 tests OK**.
- `pi --version`: 1.5.2; `pi mcp --help` confirmado.
- `scripts/verify-mcp-pi.py` pasó con base/storage temporales, red de Pi deshabilitada y sin modelo: Pi 1.5.2 conectó con exposición `direct`, descubrió cuatro herramientas y terminó una renderización `.tex` con dos artefactos. Última muestra: discovery 363.894 ms; `initialize` 58.251 ms; `tools/list` 0.111 ms; ping 0.384 ms; perfiles directo/MCP 1.865/2.025 ms; metadata 0.062/0.148 ms; enqueue 0.632/0.565 ms; status 0.294/0.562 ms. Es una muestra local, no benchmark ni afirmación de mejora de modelo o VRAM.
- No se comprobó el TUI `/mcp` manual, la configuración persistente de la Pi del usuario, compilación PDF ni ejecución web+MCP concurrente. El script comprueba la conexión real de Pi CLI usando una carpeta de configuración global temporal.
- El usuario confirmó que la otra persona terminó la validación de `demo` y autorizó crear el PR. Se hizo `git fetch origin demo`: el target remoto es `9b3e51d`, igual que la referencia local y ancestro de esta rama. `gh pr list` no encontró PR existente; `gh auth status` confirmó sesión válida.
- Un intento de `pi --approve mcp list --json` falló porque esa combinación de opciones no está admitida; no repetir ni describirlo como fallo del servidor. El comando verificado es `pi mcp list --json` dentro del script aislado.
- `git diff --check` pasó; `rg` no encontró whitespace final en los archivos cambiados.

## Continuación obligatoria

1. Al abrir la siguiente sesión, seguir `AGENTS.md`: revisar `git status --short --branch`, leer `odd/tasks/rose-documents-mcp.md` hasta `## Log` y consultar `docs/production-plan.md` antes de tocar código.
2. Revisar todas las diferencias, incluyendo archivos untracked; no resetear/limpiar ni sobrescribir nada. Ejecutar suite y prueba Pi después de cualquier cambio.
3. La validación de `demo` fue confirmada por el usuario. Tras `git fetch origin demo`, el commit observado fue `9b3e51d`, ancestro de esta rama. Revalidar remoto y ancestría antes de publicar, por si cambian mientras se completa el PR.
4. La revisión local se realizó en esta sesión, pero no hubo revisor independiente de segundo agente. La autorización actual permite crear el commit y el PR; completar/verificar T5 mediante revisión posterior, publicar solo la rama de feature y abrir el PR con base `demo`. No fusionar.
5. Informar de cualquier limitación de permisos/credenciales para crear el PR; no guardar secretos en archivos ni logs.
