# Arquitectura — H1 (convertidor)

## Flujo

```text
entrada .md/.txt
  → validación (extensión, tamaño, bytes UTF-8, control chars)
  → parser determinista → AST tipado (Document)
  → resolución de branding (perfil TOML versionado, provisional declarado)
  → generador LaTeX (escape estricto, sin LaTeX crudo)
  → plantilla versionada (sustitución estricta de tokens)
  → política LaTeX (lista blanca de paquetes y construcciones prohibidas)
  → [opcional] sandbox de contenedor → PDF
  → artefactos por trabajo + manifest.json con SHA-256
```

Sin LLM en ningún paso. Sin red. Sin estado global.

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `core/errors.py` | Errores con `code` estable y `exit_code`. |
| `core/config.py` | Configuración por entorno (`ROSE_*`) y defaults. |
| `studio/model.py` | AST tipado (`Document`, bloques, inlines) y `plain_text`. |
| `studio/parser.py` | MD/TXT → `Document` (bloques + inlines + front matter). |
| `studio/latex.py` | `Document` → cuerpo LaTeX; escape y validación de URLs. |
| `studio/template.py` | Render estricto de `{{token}}` con tokens desconocidos como error. |
| `studio/branding.py` | Carga y valida `branding/profiles/<name>/profile.toml`. |
| `studio/pipeline.py` | Orquesta conversión, assets, manifiesto y compilación. |
| `security/latex_policy.py` | Escanea el `.tex` final: construcciones y paquetes. |
| `security/sandbox.py` | Runtime de contenedor, flags de endurecimiento, ejecución. |
| `storage/artifacts.py` | Job dir atómico, hashing, escritura de manifiesto. |
| `cli.py` | `rose convert`, `rose brands`, `rose doctor`. |

## Subset de Markdown soportado

Bloques: encabezados `#`–`#####`, párrafos, listas simples (`-`, `*`, `+`,
`1.`), cita (`>`), bloque de código con fence (```` ``` ```` o `~~~`), tabla de
tuberías con fila separadora, regla horizontal, imagen en bloque
`![alt](ruta)` y front matter delimitado por `---`.

Inlines: `**fuerte**`, `*énfasis*`, `` `código` ``, `[texto](url)` y escapes
`\` para puntuación Markdown.

**Rechazado explícitamente** con error de validación: HTML/LaTeX crudo, listas
anidadas, imágenes inline, `#####`/`######` (nivel 6), tablas de más de 12
columnas, fences sin cierre y bloques de código que contengan
`\end{verbatim}`. Las `.txt` se tratan como texto plano: sin interpretar
Markdown, con párrafos separados por líneas en blanco.

## Front matter

`title`, `subtitle`, `author`, `date`, `brand`, `lang`. Claves desconocidas son
error (`front_matter_unknown_key`): no se aceptan metadatos que el sistema
ignore en silencio.

## Artefactos por trabajo

```text
build/<job-id>/
├── manifest.json          # procedencia, hashes, estado, avisos
├── source/<original>      # copia inmutable de la entrada
├── assets/                # imágenes saneadas y copiadas
└── document.tex           # LaTeX generado
```

`manifest.json` incluye `schema_version`, `job_id`, `status` (`tex-only` o
`compiled`), hashes de entrada y artefactos, perfil de branding con su marca
`provisional`, runtime e imagen usados, duración y avisos. El nombre del
directorio no participa en la reproducibilidad: el `.tex` no contiene tiempos.

## Configuración (entorno)

| Variable | Default | Uso |
|---|---|---|
| `ROSE_BRANDING_DIR` | `branding` | Raíz de perfiles y plantillas. |
| `ROSE_OUTPUT_DIR` | `build` | Directorio de trabajos. |
| `ROSE_MAX_INPUT_BYTES` | `2097152` | Límite de entrada. |
| `ROSE_MAX_IMAGE_BYTES` | `8388608` | Límite por imagen. |
| `ROSE_CONTAINER_RUNTIME` | *(auto)* | `podman` o `docker`. |
| `ROSE_SANDBOX_IMAGE` | *(vacío)* | Imagen fijada por digest. |
| `ROSE_COMPILE_TIMEOUT_SECONDS` | `90` | Timeout de compilación. |
| `ROSE_COMPILE_MEMORY` | `1g` | RAM del contenedor. |
| `ROSE_COMPILE_CPUS` | `1.0` | CPUs del contenedor. |
| `ROSE_COMPILE_PIDS` | `128` | Límite de PIDs. |

No se leen archivos `.env` automáticamente; el operador exporta las variables o
las pasa por CLI.

## Códigos de salida

| Exit | Significado |
|---|---|
| 0 | Éxito. |
| 2 | Entrada inválida o branding inválido. |
| 3 | Violación de política de seguridad. |
| 4 | Sandbox no disponible (runtime o imagen). |
| 5 | La compilación LaTeX falló. |
| 1 | Error interno inesperado. |
