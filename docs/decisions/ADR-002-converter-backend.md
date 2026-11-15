# ADR-002 — Backend de conversión Markdown → LaTeX

- **Estado:** aceptado (revisable al instalar Pandoc)
- **Fecha:** 2026-11-15
- **Contexto:** la compilación del documento exige determinismo, escape
  estricto y cero LaTeX crudo no confiable. Pandoc está ausente en el host y no
  se instalan dependencias globales sin autorización.

## Decisión

Implementar un convertidor **propio, determinista y sin dependencias** para un
subconjunto documentado de Markdown, detrás de una interfaz
(`parse_markdown` / `render_body`) que permita sustituirlo por un backend Pandoc
más adelante sin tocar el pipeline, el branding ni la política de seguridad.

## Motivos

1. **Control del escape.** Cada carácter se escapa con una tabla explícita; no
   hay paso de `raw_tex` que desactivar ni semántica de Pandoc que confiar.
2. **Reproducibilidad.** La salida no depende de la versión de un binario
   externo ni de sus extensiones habilitadas.
3. **Verificabilidad.** El AST intermedio es tipado y testeable por unidad.
4. **Cero instalaciones.** Respeta la restricción de no instalar globalmente.
5. **Errores comprensibles.** Lo no soportado falla con código estable en lugar
   de degradarse en silencio.

## Costos asumidos

- No soportamos todo CommonMark: el subset está en `docs/architecture.md` y lo
  demás se rechaza con `unsupported_construct`.
- Referencias, notas al pie, listas anidadas y tablas con alineación quedan para
  incrementos posteriores.

## Camino de salida

Si se autoriza Pandoc, se agrega `PandocMarkdownConverter` con
`-f markdown-raw_tex` y `--to latex`, se compara su AST contra el nuestro con los
10 fixtures y solo se promueve si el `.tex` resultante pasa la misma política de
seguridad y las mismas pruebas.
