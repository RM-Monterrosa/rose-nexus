# Modelo de amenazas — H1

Alcance: convertidor CLI y compilación LaTeX. Sin API, sin usuarios remotos, sin
LLM todavía. Documento vivo.

## Activos

1. Documentos originales y resultados del usuario.
2. El host de desarrollo y sus archivos (`~/.ssh`, credenciales, repositorios).
3. La cadena de suministro de la imagen contenedora.
4. La integridad del `.tex` producido (debe ser exactamente lo convertido).

## Niveles de confianza

| Nivel | Ejemplo | Trato |
|---|---|---|
| Confiable | código de `backend/`, plantillas de `branding/templates/` | se ejecuta/interpola |
| Semi-confiable | perfiles `branding/profiles/*/profile.toml` | se valida contra esquema |
| No confiable | `.md`, `.txt`, imágenes, nombres de archivo | datos; nunca instrucciones |

## Amenazas y controles

| # | Amenaza | Control implementado |
|---|---|---|
| T1 | Inyección LaTeX en el contenido (`\write18`, `\input`) | Escape carácter por carácter; el contenido nunca se interpreta como LaTeX. |
| T2 | `shell-escape` habilitado | `-no-shell-escape` fijo + política que rechaza `\write18` y `\ShellEscape`. |
| T3 | Fuga de archivos del host vía `\input{/etc/passwd}` | Política rechaza rutas absolutas y `..`; el contenedor solo monta `/src` y `/out`. |
| T4 | Path traversal en imágenes `![](../../.ssh/id_rsa)` | Resolución canónica, `is_relative_to(source_dir)`, rechazo de symlinks y de rutas absolutas. |
| T5 | Imagen gigante o bomba de descompresión | Límite de bytes por imagen antes de copiar; extensión en lista blanca. |
| T6 | Entrada gigante o patológica | Límite de bytes, de bloques y de columnas; control chars rechazados. |
| T7 | Escritura fuera del job dir | Todo se escribe bajo un directorio temporal dentro de `out`; se renombra al final; sin rutas derivadas del nombre de archivo del usuario (se sanea el slug). |
| T8 | Escape del contenedor | Sin red, rootfs de solo lectura, `nobody`, `cap-drop=ALL`, `no-new-privileges`, límites de CPU/RAM/PIDs/tiempo. |
| T9 | Imagen mutable comprometida | Solo digest `@sha256:`, sin tags. |
| T10 | Fuga de contenido por logs | El manifiesto guarda hashes y rutas relativas; el error de compilación incluye un extracto de `stderr`/`stdout` **acotado a 4000 caracteres** con marca de truncamiento, y no se persiste ningún archivo de log en el job. |
| T11 | Sustitución de tokens en plantilla | Render estricto: token desconocido o valor que reinyecta `{{` es error. |
| T12 | Ejecución de scripts remotos | Fuera de alcance por regla: no se descarga ni ejecuta nada. |

## Riesgos residuales

- El aislamiento depende del runtime del contenedor y de su configuración de
  namespaces; `rose doctor` lo reporta y el manifiesto lo registra.
- El PDF puede contener metadatos del compilador; no se promete anonimización.
- Sin TeX provisionado, el flujo PDF está deshabilitado (no hay camino inseguro
  alternativo).
- LaTeX es Turing-completo: la política es defensa en profundidad, no prueba
  formal. El control primario es el escape total del contenido + el sandbox.

## Pruebas de seguridad exigidas

`tests/security/` cubre: traversal de imágenes, LaTeX crudo neutralizado,
`\write18` en el contenido, URLs `javascript:`/`file:`, extensión inválida,
entrada no UTF-8, límites de tamaño, sentinel `\end{verbatim}` y flags del
contenedor verificados sobre un runtime simulado.
