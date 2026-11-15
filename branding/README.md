# Branding

Sistema de marca versionado para el pipeline de documentos.

## Fuente

- Repositorio: `https://forgejo.invering.com/INVERING/BRANDING.git`
- Rama: `main` · Commit fijado: `bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2`
- Versión: `4.1-logo-greens` · Ver `docs/decisions/ADR-004-branding-source.md`

No se ejecuta ningún script del repositorio de branding. Se inspeccionan tokens,
documentación y assets; los activos usados se copian con SHA-256 registrado.

## Perfiles

| Perfil | Estado | Paleta | Nota |
|---|---|---|---|
| `invering` | corporativo, no provisional | verdes INVERING | **Predeterminado**; exige `source` con commit. |
| `demo` | **provisional** | rosa + azul | Solo con `--brand demo`; sin pretensión corporativa. |

Reglas:

1. Un perfil `provisional = false` **debe** declarar `source` (commit exacto).
2. El `.tex` generado declara perfil, versión y si es provisional.
3. Prohibido inferir colores, logos o tipografías que no estén en el perfil.
4. `BRAND-LOCK.md` prohíbe acentos cálidos en marca INVERING y desaconseja la
   estética «SaaS azul»: por eso rosa+azul solo existe en el perfil provisional.

## Estructura

```text
profiles/<name>/profile.toml   tokens y declaración de procedencia
templates/document.tex.tmpl    plantilla LaTeX versionada
assets/                        logos y recursos con procedencia
fonts/                         solo fuentes con licencia verificada
```

## Assets

- `assets/invering/logo-official.png` — del commit citado.
- `assets/invering/symbol-square.png` — del commit citado.

Las licencias de Archivo e IBM Plex **no** están declaradas en el repositorio de
origen; no se empaquetan hasta verificarlas.
