# Feature: H1 — Convertidor CLI determinista .md/.txt → .tex → .pdf

**Estado:** en curso · **Rama:** `feat/h1-converter-cli` · **Plan:** `docs/production-plan.md` (v0.2)

## Specs

- **S1** — «Estamos comenzando el desarrollo de **Rose Nexus**.» Alcance de esta
  feature: preparar el repositorio y el convertidor. Nada de fases posteriores.
- **S2** — «Preparar el backend en Python.» Paquete `backend/rose_nexus`, CLI
  ejecutable, sin dependencias de terceros.
- **S3** — «Desarrollar un convertidor CLI de Markdown/TXT a LaTeX y PDF.»
  `rose convert SRC --brand NAME --out DIR` produce `.tex` y, si el sandbox está
  aprovisionado, `.pdf`.
- **S4** — «Diseñar el sistema de branding mediante plantillas versionadas.»
  Perfil TOML + plantilla LaTeX versionados, validados y con marca de
  procedencia en el `.tex` y en el pie del documento.
- **S5** — «Utilizar código determinista para la conversión, no IA.»
  Misma entrada ⇒ mismo `.tex` byte a byte; ninguna llamada a modelo.
- **S6** — «No incorporar todavía OCR, MCP, multiagentes ni interfaces complejas.»
- **S7** — «No inventar el branding corporativo. Si la rama `Branding` no está
  disponible, utilizar un perfil provisional.»
- **S8** — «La compilación de documentos no confiables debe ejecutarse en un
  sandbox real.» Sin runtime o sin imagen no hay PDF; nunca se compila en el host.
- **S9** — «No ejecutar scripts descargados de internet sin inspeccionarlos.»
- **S10** — «No instalar dependencias globales ni eliminar archivos sin
  autorización.»
- **S11** — «Preparar pruebas automatizadas y documentos de ejemplo.» 10
  fixtures + suite unitaria, de integración y de seguridad.
- **S12** — «Trabajaremos incrementalmente, manteniendo el código documentado y
  verificable.» Commits por unidad y documentación en `docs/`.
- **S13** — «Aquí tengo el repo de branding https://forgejo.invering.com/INVERING/BRANDING.git…
  Y cuando hagas el diseño, puede que sea en una combinacion de rosa y de azul.
  Agregalo en el md para siempre tenerlo presente estas cosas.»
  Registrado en `docs/decisions/ADR-004-branding-source.md` y en `AGENTS.md` §6.
  El repo real sustituye a la «rama `Branding`» del plan (rama `main`, commit
  `bd5dd8a`). La dirección rosa+azul choca con `BRAND-LOCK.md` (prohíbe acentos
  cálidos y desaconseja «SaaS azul»); por eso vive solo en el perfil `demo`
  provisional y la identidad canónica queda como decisión del usuario.

## Tasks

| ID | Spec | Ruta | Commit |
|---|---|---|---|
| T1 | S1, S2, S10 | Andamiaje, `AGENTS.md`, plan renombrado, ADR-001/002/003 | `9027d75` |
| T2 | S4, S7, S13 | Perfiles `invering`/`demo`, plantilla, activos, ADR-004 | `39354ed` |
| T3 | S5, S6 | Modelo tipado + parser determinista MD/TXT | `107e97b` |
| T4 | S5, S4 | Generador LaTeX escapado + render estricto de plantilla | `1c19467` |
| T5 | S8, S9, S10 | Política LaTeX, sandbox de contenedor, artefactos | `d5acca1` |
| T6 | S3, S11 | Pipeline de trabajos, 11 fixtures, integración y seguridad | `a38d9d6` |
| T7 | S3, S12 | CLI `convert`/`brands`/`doctor` | `1395fba` |

## Slices (unidad de revisión)

La feature se entregó en **7 commits secuenciales** sobre `feat/h1-converter-cli`,
ordenados por dependencia y agrupados por comportamiento (implementación y sus
pruebas en el mismo commit):

```text
9027d75 docs(h0)      plan, AGENTS.md, ADRs, arquitectura, amenazas
39354ed feat(branding) perfiles + plantilla + activos INVERING verificados
107e97b feat(studio)  modelo tipado + parser
1c19467 feat(studio)  LaTeX escapado + plantilla estricta
d5acca1 feat(security) política LaTeX + sandbox + artefactos
a38d9d6 feat(studio)  pipeline + fixtures + integración/seguridad
1395fba feat(cli)     convert/brands/doctor
```

El total supera la guía de ~400 líneas por commit porque es el arranque del
repositorio (andamiaje + documentación incluidos). Los cortes son por
comportamiento verificable, no por cantidad de archivos. **Push y PR quedan como
decisión del usuario**; no se publicó nada.


## Log

- **L1** (solicitud original, verbatim):

  > Estamos comenzando el desarrollo de **Rose Nexus**.
  >
  > Lee primero `docs/production-plan.md` y úsalo como referencia técnica principal.
  >
  > Quiero iniciar las fases H0 y H1.
  >
  > **Tu primera tarea:**
  > 1. Inspeccionar el entorno de desarrollo y las dependencias disponibles.
  > 2. Crear la estructura mínima del repositorio.
  > 3. Crear un archivo `AGENTS.md` con las reglas de desarrollo, seguridad y pruebas.
  > 4. Preparar el backend en Python.
  > 5. Desarrollar un convertidor CLI de Markdown/TXT a LaTeX y PDF.
  > 6. Diseñar el sistema de branding mediante plantillas versionadas.
  > 7. Preparar pruebas automatizadas y documentos de ejemplo.
  >
  > **Restricciones:**
  > - Utilizar código determinista para la conversión, no IA.
  > - No incorporar todavía OCR, MCP, multiagentes ni interfaces complejas.
  > - No inventar el branding corporativo. Si la rama `Branding` no está disponible, utilizar un perfil provisional.
  > - La compilación de documentos no confiables debe ejecutarse en un sandbox real.
  > - No ejecutar scripts descargados de internet sin inspeccionarlos.
  > - No instalar dependencias globales ni eliminar archivos sin autorización.
  >
  > Antes de implementar, explícame brevemente la estructura propuesta y las dependencias necesarias.
  >
  > Después desarrolla el primer incremento, ejecuta las pruebas y muéstrame los resultados.
  >
  > Trabajaremos incrementalmente, manteniendo el código documentado y verificable.

- **L2** — El plan estaba en `docs/Rose_Nexus_Plan_de_Produccion_v0.2.md`; se
  renombra a `docs/production-plan.md` (ruta que el plan prescribe y que pidió el
  usuario). Contenido sin cambios.
- **L3** — Entorno medido: Fedora 45, Python 3.15.2, sin Pandoc ni TeX, con
  Docker 29.9.3 y Podman 6.1.3. Decisiones: ADR-002 (convertidor propio,
  stdlib) y ADR-003 (sandbox de contenedor con digest). Consecuencia: el `.tex`
  se produce hoy; el PDF queda deshabilitado hasta aprovisionar la imagen.
- **L4** — `.env.example` fue bloqueado por la política de rutas sensibles del
  harness. Las variables `ROSE_*` se documentan en `docs/architecture.md`; el
  usuario se ofreció a crear el `.env` local con esos valores.
- **L5** — El usuario indicó el repositorio real de branding
  (`https://forgejo.invering.com/INVERING/BRANDING.git`) y la dirección visual
  «rosa y azul» para el diseño. Inspección de solo lectura del commit
  `bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2` (sistema `4.1-logo-greens`): la
  paleta real es verde/bosque/hueso y `BRAND-LOCK.md` prohíbe acentos cálidos y
  desaconseja «SaaS azul». Decisión registrada en `ADR-004` y `AGENTS.md` §6:
  dos perfiles (`invering` verificado, `demo` provisional rosa+azul). No se
  ejecutó ningún script del repositorio de branding. No se inventó ningún token:
  los verdes salen de `colors/palette.md`; el rosa/azul es placeholder explícito
  del perfil provisional.
