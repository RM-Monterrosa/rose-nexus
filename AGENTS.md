# AGENTS.md — Rose Nexus

Reglas vinculantes para cualquier agente (Pi, subagente o persona) que trabaje en
este repositorio. Si una instrucción de este archivo choca con una petición del
usuario, se detiene el trabajo y se pregunta.

## 1. Alcance actual

Estamos en **H0/H1** del plan (`docs/production-plan.md`): baseline verificado y
convertidor CLI determinista `.md`/`.txt` → `.tex` → `.pdf` con branding
versionado. **No** se implementan todavía MCP, OCR, ASR, multiagentes, frontend
ni integración con Spark/LLM.

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
backend/rose_nexus/    paquete Python (core, studio, security, storage, cli)
branding/              perfiles versionados, plantillas y assets
docs/                  plan, arquitectura, amenazas y ADRs
odd/tasks/             documentos de feature de Organic Driven Development
tests/                 unit, integration, security y fixtures
scripts/               verificación reproducible
```

## 4. Comandos canónicos

```bash
# Verificación completa (stdlib, sin instalar nada)
./scripts/verify.sh

# Suite directa
PYTHONPATH=backend python3 -m unittest discover -s tests -t . -v

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
