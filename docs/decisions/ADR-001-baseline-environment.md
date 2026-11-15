# ADR-001 — Baseline de entorno (H0)

- **Estado:** aceptado
- **Fecha:** 2026-11-15
- **Contexto:** H0 exige registrar el entorno real antes de prometer capacidades.

## Entorno medido (estación de desarrollo, no Spark)

| Elemento | Valor |
|---|---|
| SO | Fedora Linux 45 (KDE Plasma Desktop Edition) |
| Kernel | 7.3.3-300.fc45.x86_64 |
| Python | 3.15.2 (stdlib `tomllib` disponible) |
| venv | funcional |
| Docker | 29.9.3 |
| Podman | 6.1.3 |
| Pandoc | **ausente** |
| Motores TeX (`xelatex`, `pdflatex`, `lualatex`, `latexmk`) | **ausentes** |
| Tectonic | ausente |
| uv / ruff / pytest | ausentes (no se instalan globalmente) |
| Red hacia PyPI | disponible |
| RAM / disco (`/home`) | 15 GiB / 388 GiB libres |

No se midió la instancia Spark (RTX 3060 12 GB): `nvidia-smi`, VRAM real,
versión de Pi y exposición de red siguen pendientes. Este ADR **no** declara
nada sobre GPU.

## Consecuencias

1. No hay Pandoc ni TeX en el host, y no se instalan dependencias globales sin
   autorización. Ver ADR-002 (backend de conversión) y ADR-003 (sandbox).
2. Hay Docker y Podman: el aislamiento real es viable; la imagen es el faltante.
3. La suite debe correr con biblioteca estándar únicamente (`unittest`), porque
   `pytest` no está instalado.
4. `rose doctor` es el registro reproducible de este baseline y debe reejecutarse
   en Spark antes de fijar benchmarks de LLM.

## Pendientes registrados

- Verificar `nvidia-smi`, VRAM utilizable, driver/CUDA y versión de Pi en Spark.
- Inspeccionar la rama `Branding` (repo, permisos, licencias de fuentes) y
  reemplazar el perfil `demo` provisional.
- Definir la imagen TeX y aprobar su descarga.
