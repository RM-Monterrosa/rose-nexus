# ADR-008 — Presupuesto exacto de contexto para inferencia local (H4)

- **Estado:** aceptado
- **Fecha:** 2026-11-15
- **Contexto:** H3 estableció un cliente local compatible con OpenAI, limitado a
  loopback y con un único slot. Su configuración incluía
  `ROSE_LLM_CONTEXT_TOKENS`, pero todavía no medía el prompt renderizado por el
  servidor. Contar caracteres o aplicar una tokenización heurística no basta:
  la plantilla de chat, el historial, Unicode y los tokens especiales cambian el
  consumo real de contexto.

## Decisiones

### 1. Medición con el modelo y la plantilla del servidor

`ContextPreflight` usa exclusivamente la ruta nativa de `llama.cpp`, en este
orden y para cada intento de generación:

1. `GET /props` lee `default_generation_settings.n_ctx`.
2. `POST /apply-template` renderiza la secuencia completa de mensajes con
   `add_generation_prompt=true`.
3. `POST /tokenize` cuenta ese prompt renderizado con `add_special=false` y
   `parse_special=true`.

Es la ruta exacta de medición consciente del modelo: no hay tokenizador local,
estimación por caracteres ni fallback heurístico. El resultado conserva solo
`server_context_tokens` y `prompt_tokens`, nunca el contenido de los mensajes.

### 2. Presupuesto fail-closed y reserva explícita de generación

`ROSE_LLM_CONTEXT_TOKENS` es un límite superior efectivamente aplicado, no un
valor declarativo. Para cada solicitud:

```text
contexto_efectivo = min(ROSE_LLM_CONTEXT_TOKENS, n_ctx_del_servidor)
tokens_requeridos = rendered_prompt_tokens + max_tokens
```

Si `max_tokens > contexto_efectivo`, la reserva de generación es incompatible y
se rechaza con `inference_configuration_invalid`. Si
`rendered_prompt_tokens + max_tokens > contexto_efectivo`, se rechaza con
`prompt_too_long`, informando los conteos numéricos. Ambos son errores de
configuración/entrada con exit 2 en la CLI.

La medición y `ContextBudget.evaluate` se ejecutan **antes** de adquirir el
semáforo y antes de llamar a `/chat/completions`. Un presupuesto excedido, una
reserva incompatible o el fallo de cualquiera de los tres endpoints impide la
generación y no consume el slot. No se recorta automáticamente el prompt, no se
resume el historial y no se reduce silenciosamente `max_tokens`.

### 3. Mismo transporte y mismas políticas de H3

Los tres endpoints usan `OpenAICompatibleProvider` y la biblioteca estándar;
no se agrega ningún SDK ni dependencia. Comparten con las llamadas H3:

- validación del endpoint y resolución DNS en tiempo de llamada, exigiendo que
  todas las direcciones sean loopback salvo el opt-in remoto ya regulado;
- rechazo de credenciales en la URL y de esquemas distintos de `http`/`https`;
- bloqueo de redirecciones, timeouts acotados y ausencia de reintentos;
- límite de respuesta de 2 MiB y validación estricta de JSON y de sus campos;
- redacción de prompts, historial y API key en detalles de error, y métricas sin
  contenido.

Timeouts e indisponibilidad conservan exit 4; errores HTTP y de protocolo,
exit 5. Un servidor que no ofrezca estas rutas o devuelva una forma incompatible
falla de manera cerrada: no se sustituye la medición por una aproximación.

### 4. Contratos públicos estables y avisos de truncamiento

`Answer` y las respuestas JSON de la CLI conservan su forma. En la salida humana
de `llm ask`, `finish_reason="length"` agrega en stderr el aviso de que la
respuesta puede estar incompleta; la web muestra el aviso equivalente junto a la
respuesta. Estos avisos describen el agotamiento de `max_tokens` durante una
generación admitida, no sustituyen el rechazo previo de un prompt que excede el
contexto. La salida JSON no añade ese aviso textual y expone el mismo
`finish_reason` dentro de las métricas.

### 5. Evidencia viva y alcance de la exactitud

La sonda sintética opt-in contra el `llama.cpp` local comparó el conteo de
`ContextPreflight` con `usage.prompt_tokens` de la completión, usando
`max_tokens=1` y `temperature=0`:

| Caso | Sonda manual, preflight = usage | Prueba opt-in, preflight = usage | Deltas |
|---|---:|---:|---:|
| ASCII, sistema + usuario | 25 = 25 | 22 = 22 | 0 / 0 |
| Historial con `<|im_start|>` / `<|im_end|>` literales | 44 = 44 | 46 = 46 | 0 / 0 |
| Unicode: acentos, marcas combinantes, emoji y CJK | 40 = 40 | 32 = 32 | 0 / 0 |

Las dos series usaron entradas sintéticas distintas y obtuvieron delta 0 en sus
seis comparaciones. Por eso sus valores absolutos difieren sin contradecirse y
no se justifica añadir un margen correctivo para estos casos calibrados. La
prueba viva compara únicamente conteos y metadatos de finalización; no fija ni
registra el texto generado.

Esta evidencia no demuestra cobertura para otros modelos, otras plantillas de
chat ni todas las versiones futuras del servidor. Si una calibración futura
observa una diferencia, debe medirse y resolverse antes de volver a declarar el
conteo exacto; no se inventa un margen.

## Alternativas descartadas

| Alternativa | Motivo |
|---|---|
| Estimar tokens por caracteres | Ignora tokenizador, plantilla, historial y Unicode |
| Tokenizador local o SDK nuevo | Duplica la lógica del servidor y agrega dependencias |
| Truncar o resumir automáticamente | Altera la solicitud sin consentimiento y puede perder fuentes |
| Reducir `max_tokens` silenciosamente | Oculta la incompatibilidad y cambia el contrato de salida |
| Medir después de generar | Consume el slot y detecta el problema demasiado tarde |

## Consecuencias y límites

- Cada intento de `ask`, cada ejecución de `bench` y cada envío web admitido hace
  tres llamadas loopback adicionales antes de la completión.
- `ROSE_LLM_CONTEXT_TOKENS` puede restringir una ventana de servidor mayor; un
  `n_ctx` menor del servidor siempre impone el límite más estricto.
- Un futuro troceado o resumen podrá reutilizar `ContextBudget` y referencias
  estables a las fuentes, pero deberá preservar la medición y el consentimiento
  explícitos.
- MCP, RAG completo, Inbox y agentes autónomos siguen fuera de alcance. El modelo
  sigue devolviendo texto como borrador, sin herramientas ni acciones.
