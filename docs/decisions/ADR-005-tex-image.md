# ADR-005 — Imagen TeX del sandbox

- **Estado:** aceptado y verificado
- **Fecha:** 2026-11-15
- **Contexto:** sin motor TeX en el host y con la prohibición de compilar fuera
  del sandbox (ADR-003), el PDF quedaba deshabilitado. H2 lo necesita para su
  criterio de cierre.

## Imagen

| Dato | Valor |
|---|---|
| Base | `docker.io/library/debian:bookworm-slim` |
| Contenido | `texlive-xetex`, `texlive-latex-recommended`, `texlive-latex-extra`, `texlive-fonts-recommended`, `lmodern` |
| Definición versionada | `deploy/sandbox/texlive/Dockerfile` |
| Build reproducible | `./scripts/build-teximage.sh` |
| Motor | XeTeX 3.141592653-2.6-0.999994 (TeX Live 2022/Debian) |
| Tamaño | 649 MB |
| Digest verificado | `sha256:df14fa433c90f8ccc1f6f7a4b772bb653edaa7adeb99e1a698ba19cb4434a970` |
| Referencia usada | `rose-nexus/texlive-sandbox@sha256:df14fa43…a970` |

El digest es **local a esta máquina** (imagen construida, no publicada). Es
content-addressed y se fija igual que una imagen de registro; el script lo obtiene
de `image inspect --format '{{.Digest}}'`, no del image id (el id no resuelve como
referencia). En otra máquina, reconstruir produce otro digest y hay que volver a
exportar `ROSE_SANDBOX_IMAGE`.

## Paquetes exigidos por la plantilla

Verificados dentro de la imagen con `kpsewhich`: `geometry`, `graphicx`,
`array`, `longtable`, `xcolor`, `hyperref`, `fancyhdr`. `draftwatermark` solo se
usa si un perfil declara marca de agua; `texlive-latex-extra` lo cubre.

No se empaquetan Archivo ni IBM Plex: sus licencias no están declaradas en el
repo de branding. Mientras `fonts_verified = false`, la plantilla no llama a
`fontspec` y el PDF usa Latin Modern.

## Montaje: SELinux obliga a `:Z`

Verificado empíricamente en Fedora con SELinux `Enforcing`:

| Forma | Resultado |
|---|---|
| `--mount type=bind,src=…,dst=/src,ro` | `xelatex: document.tex: Permission denied` |
| `-v …:/src:ro,Z` | compila |
| `--security-opt label=disable` | compila (descartado: debilita el aislamiento) |

Decisión: sintaxis de volumen con `:Z` (etiqueta privada) en entrada y salida.
El fallo era del kernel/SELinux, no de permisos de archivo: el directorio ya era
`0755`. Documentado también en ADR-003.

## Evidencia de cierre (H1)

Con la imagen fijada, `rose doctor` reporta `ready_to_compile: true` y los 11
fixtures producen PDF real (validados con lector PDF):

| Fixture | Páginas | Imágenes |
|---|---|---|
| 10 documentos `.md` | 2 cada uno | logo INVERING (1); 06-image suma el PNG del documento (2) |
| 10-frontmatter (perfil `demo`) | 2 | 0 (perfil provisional sin logo) |
| 11-plain.txt | 2 | logo |

Total: 22 páginas. Títulos y acentos se extraen correctamente del PDF.

## Reconstruir o actualizar

```bash
./scripts/build-teximage.sh rose-nexus/texlive-sandbox:0.2.0
export ROSE_SANDBOX_IMAGE="rose-nexus/texlive-sandbox@sha256:<nuevo digest>"
PYTHONPATH=backend python3 -m rose_nexus.cli doctor   # ready_to_compile: true
```

Subir de versión exige recompilar los fixtures y registrar el digest nuevo: un
cambio de imagen puede cambiar el PDF aunque el `.tex` sea idéntico.

## Pendientes conocidos

- Los PDF no llevan `/Title` en metadatos (`\hypersetup` no se emite todavía).
- Sin publicar en un registro: el digest es local, no portable entre máquinas.
- Sin `babel`: la partición de palabras en español usa reglas inglesas.
