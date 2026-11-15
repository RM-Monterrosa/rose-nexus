Objetivo: implementar H4, control exacto de contexto y presupuesto de tokens para el cliente LLM.
Rama tracker: feat/h4-llm-context-budget (base feat/h3-llm-client) · Entrega: feature-branch-chain · Pronóstico: 900–1300 líneas de autoría.
Runner: PATH="$PWD/.venv/bin:$PATH" ./scripts/verify.sh · Pruebas focales con PYTHONPATH=backend y .venv/bin/python.

## Specs

- S1: «Mantén la arquitectura propuesta: `ContextPreflight`, `/props`, `/apply-template` y `/tokenize`, sin dependencias adicionales.» Comprobación: preflight común, conteo del prompt renderizado y contexto efectivo limitado por configuración y servidor.
- S2: «Verifica la concordancia del conteo previo con `usage.prompt_tokens`, incluyendo plantilla, historial y tokens especiales. Si existe una diferencia, documenta y resuelve el margen antes de declarar el conteo exacto.» Comprobación: prueba viva opt-in con entradas sintéticas y evidencia numérica sin contenido.
- S3: «Aplica las mismas políticas de seguridad, anti-SSRF, timeouts y privacidad de H3 a todos los endpoints nuevos.» Comprobación: casos de DNS, redirecciones, límites, timeouts y ausencia de contenido o claves en salidas y métricas.
- S4: «Si el presupuesto se supera, el preflight falla o la configuración del servidor resulta incompatible, rechaza la generación sin truncamientos ni ajustes silenciosos.» Comprobación: completion no se invoca, no se adquiere el slot y el error es tipificado y claro.
- S5: «Conserva las interfaces actuales de CLI y web, así como el aislamiento de H1/H2/H3.» Comprobación: contratos previos y suite completa; cambios visibles limitados a errores y avisos necesarios.
- S6: «Implementa las pruebas propuestas, incluyendo límites, Unicode, errores y validación real opt-in contra llama.cpp.» Comprobación: límites exactos, historial, Unicode, fallos de cada endpoint y prueba viva opt-in.
- S7: «Documenta la arquitectura en ADR-008 y actualiza las instrucciones pertinentes» Comprobación: ADR nuevo y documentación/configuración de inferencia coherentes con el comportamiento.
- S8: «No implementar todavía MCP, RAG completo, Inbox ni agentes autónomos.» Comprobación: diff limitado al cliente LLM, sus superficies, pruebas y documentación.
- S9: «No modifiques H1/H2/H3 innecesariamente, no fusiones PR y no invoques la revisión nativa previamente descartada.» Comprobación: sin cambios fuera de la integración H4 necesaria, sin fusiones ni llamadas de revisión nativa.

## Tasks

- T1 · S1-S3,S6,S9 · parent inline · done · RED: módulo context ausente (1 error de importación) → GREEN: 49 pruebas AI OK; commit de slice 1, hash en L7 · Transporte ContextPreflight verificado · Risk: item 2 (nuevos usos del transporte anti-SSRF y privacidad).
- T2 · S1-S6,S9 · parent inline · pending · RED/GREEN pendiente · Slice 2, rama feat/h4-context-admission: presupuesto, InferenceClient y rechazo fail-closed.
- T3 · S4-S6,S9 · parent inline · pending · RED/GREEN pendiente · Slice 3, rama feat/h4-context-surfaces: CLI/web compatible y señalización de respuestas limitadas.
- T4 · S1-S3,S6-S7 · parent inline · pending · Evidencia pendiente · Slice 4, rama feat/h4-context-docs: ADR-008, documentación, configuración y calibración viva opt-in.
- T5 · S1-S9 · parent + gentle-ai-verify · pending · Verificación completa, revisión independiente por riesgo y cierre · Risk: item 2 (seguridad de transporte y privacidad).

## Log

- L1: «Apruebo el plan técnico de **H4 — Control de contexto y presupuesto de tokens** para Rose Nexus.

Puedes crear la rama `feat/h4-llm-context-budget` basada en `feat/h3-llm-client` y comenzar la implementación.

Mantén la arquitectura propuesta: `ContextPreflight`, `/props`, `/apply-template` y `/tokenize`, sin dependencias adicionales.

**Consideraciones obligatorias:**

1. Verifica la concordancia del conteo previo con `usage.prompt_tokens`, incluyendo plantilla, historial y tokens especiales. Si existe una diferencia, documenta y resuelve el margen antes de declarar el conteo exacto.
2. Aplica las mismas políticas de seguridad, anti-SSRF, timeouts y privacidad de H3 a todos los endpoints nuevos.
3. Si el presupuesto se supera, el preflight falla o la configuración del servidor resulta incompatible, rechaza la generación sin truncamientos ni ajustes silenciosos.
4. Conserva las interfaces actuales de CLI y web, así como el aislamiento de H1/H2/H3.
5. Implementa las pruebas propuestas, incluyendo límites, Unicode, errores y validación real opt-in contra llama.cpp.

Documenta la arquitectura en ADR-008 y actualiza las instrucciones pertinentes»
- L2: Baseline previa confirmada: árbol limpio, PR #1/#2/#3 abiertos; 260 pruebas OK y 1 skip usando el .venv existente. Servidor real: rose-spark-4b, n_ctx=8192, 1 slot; /apply-template y /tokenize disponibles. Rama H4 creada desde cf18a4d41f581e74a3f687fd519ff654ace50808.
- L3: Pronóstico de entrega superior a unas 400 líneas; con estrategia ask-on-risk se requirió una elección de agrupación antes del primer commit.
- L4: El usuario eligió «Cadena sobre la rama de H4 (recomendada)» (chain_strategy=feature-branch-chain). Cuatro slices dependientes: preflight → admission → surfaces → docs. Tracker PR futuro en borrador; ninguna publicación ni fusión autorizada.
- L5: Commit de tracking 093f416 sobre la rama tracker. La rama por defecto remota se verificó como main. El conteo de slices se mide desde cf18a4d/H3, no desde origin/main, porque la cadena conserva las dependencias H1→H2→H3.
- L6: Slice 1 en feat/h4-context-preflight. RED observado: ModuleNotFoundError rose_nexus.ai.context (1 error). GREEN: 24 pruebas focales de preflight/provider y luego 49 pruebas AI, todas OK. No se declaró todavía concordancia exacta con usage.prompt_tokens: esa aceptación pertenece a T4.
