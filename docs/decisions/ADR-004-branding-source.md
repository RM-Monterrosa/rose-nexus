# ADR-004 — Fuente de branding y convivencia con la identidad de producto

- **Estado:** aceptado y resuelto (identidad canónica decidida)
- **Fecha:** 2026-11-15
- **Contexto:** el usuario indicó el repositorio real de branding y adelantó una
  dirección visual para Rose Nexus.

## Fuente verificada

| Dato | Valor |
|---|---|
| Repositorio | `https://forgejo.invering.com/INVERING/BRANDING.git` |
| Rama | `main` (no existe una rama llamada `Branding`) |
| Commit inspeccionado | `bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2` |
| Versión del sistema | `4.1-logo-greens` (INVERING Brand System v4) |
| Inspección | solo lectura; **no se ejecutó** `scripts/validate_brand.py` ni ningún otro archivo del repo |

## Tokens reales (tomados de `colors/palette.md` y `ui/tokens.json`)

| Token | Hex |
|---|---|
| Bosque Digital | `#05130F` |
| Verde Profundo | `#006838` |
| Verde Medio | `#60A83D` |
| Verde Hoja | `#73B43E` |
| Verde Luz | `#8DC63F` |
| Hueso | `#F2F5EF` |

Tipografía declarada: **Archivo/Archivo Expanded** (titulares), **IBM Plex Sans**
(cuerpo), **IBM Plex Mono** (datos y código). El repositorio **no** declara
licencias de fuentes; queda pendiente verificarlas antes de empaquetarlas.

## Conflicto registrado (no resuelto por el agente)

`BRAND-LOCK.md` v4 establece dos invariantes que chocan con la dirección
«combinación de rosa y de azul» que pidió el usuario para el diseño:

> 4. Paleta: los verdes originales del logo `#006838`, `#60A83D`, `#73B43E` y
>    `#8DC63F`, apoyados por `#05130F` y `#F2F5EF`. **No introducir acentos
>    cálidos como colores de marca.**
>
> 6. Evitar **SaaS azul**, cyberpunk, hologramas, glassmorphism, glow intenso…

El rosa es un acento cálido y el azul coincide con la estética que el lock pide
evitar. Por lo tanto, una salida con marca **INVERING** no puede usar rosa+azul.
Como el agente no puede decidir la identidad del producto, se implementan dos
perfiles y la decisión queda para la persona.

## Decisión

| Perfil | Naturaleza | Paleta | Uso |
|---|---|---|---|
| `invering` | No provisional, con `source` = commit `bd5dd8a` | Verdes + Hueso + Bosque | **Predeterminado**; documentos corporativos |
| `demo` | **Provisional**, sin pretensión corporativa | Rosa (`#B03A5B`) + azul (`#1F4E79`) | Solo con `--brand demo` |

- El perfil `invering` es la única vía legítima para afirmar marca corporativa.
- El perfil `demo` declara `provisional = true` en el `.tex` y en el pie de
  página; ningún artefacto puede sugerir que es la identidad de INVERING.
- Ambos comparten el mismo esquema, la misma plantilla y las mismas pruebas.
- Activos copiados con procedencia: `branding/assets/invering/logo-official.png`
  y `symbol-square.png`, con SHA-256 registrado en el manifiesto del trabajo.
  Se copian como PNG porque SVG requiere `svg`/`shell-escape`, prohibido por
  ADR-003.

## Decisión del usuario (2026-11-15)

**`invering` es la identidad canónica** de los documentos de Rose Nexus. Es el
perfil predeterminado del pipeline y de la CLI. El perfil `demo` (rosa + azul)
queda como experimento **provisional** disponible solo con `--brand demo`, y su
salida sigue declarándose PROVISIONAL en el `.tex`, la portada, el pie y el
manifiesto.

Consecuencias:

- El default de `convert_document` y de `rose convert` es `invering`.
- Los PDF corporativos llevan logo oficial, verdes del lock y commit de origen.
- Retomar rosa+azul como identidad principal requiere un ADR nuevo: sigue
  chocando con `BRAND-LOCK.md`.

## Pendientes

- Verificar licencias de Archivo e IBM Plex antes de incluirlas en la imagen TeX.
- Confirmar si Rose Nexus usa logo de INVERING en documentos personales.
- Revalidar este ADR si la rama o el commit de branding cambian (el `source`
  del perfil es un pin, no un rango).
