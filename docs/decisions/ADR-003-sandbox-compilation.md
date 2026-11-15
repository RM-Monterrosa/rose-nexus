# ADR-003 — Compilación LaTeX en sandbox de contenedor

- **Estado:** aceptado; provisión de imagen pendiente de autorización
- **Fecha:** 2026-11-15
- **Contexto:** compilar LaTeX no confiable es ejecución de código ajeno. La
  restricción del usuario es explícita: sandbox real o flujo deshabilitado.

## Decisión

`security/sandbox.py` construye la invocación de compilación contra PODMAN o
DOCKER con este perfil mínimo, y **no existe** camino alternativo en el host:

| Control | Valor |
|---|---|
| Red | `--network=none` |
| Rootfs | `--read-only` |
| Escritura | solo `/out` (resultados) y `--tmpfs /tmp` con `nosuid,noexec` |
| Entrada | montaje de solo lectura en `/src` con reetiquetado SELinux (`-v …:ro,Z`) |
| Usuario | `65534:65534` (nobody) |
| Capacidades | `--cap-drop=ALL` |
| Escalada | `--security-opt=no-new-privileges` |
| Límites | `--memory`, `--memory-swap` igual, `--cpus`, `--pids-limit`, `--ulimit` |
| Tiempo | timeout del proceso completo con `kill` del grupo |
| Shell escape | `xelatex -no-shell-escape -interaction=nonstopmode -halt-on-error` |
| Reproducibilidad | `SOURCE_DATE_EPOCH=0`, `FORCE_SOURCE_DATE=1` |

La imagen se declara como `repo@sha256:<64 hex>` en `ROSE_SANDBOX_IMAGE`. Las
tags mutables (`:latest`) se rechazan: una imagen mutable es un vector de
suministro. Sin imagen aprovisionada, `rose convert --format pdf` falla con
`sandbox_unavailable` (exit 4) **antes** de escribir artefactos.

## Requisitos de la imagen (a construir o verificar)

`xelatex` más: `geometry`, `graphicx`, `longtable`, `array`, `xcolor`,
`hyperref`, `fancyhdr`, `fontspec`, `draftwatermark` (opcional). Sin red durante
el job: todos los paquetes van preinstalados.

## Riesgos residuales aceptados en H1

- **SELinux (Fedora, Enforcing):** `--mount type=bind` no reetiqueta y el
  contenedor no puede leer `/src` (EACCES del kernel, no de TeX). Se usa sintaxis
  de volumen con `:Z` (etiqueta privada del contenedor). Verificado
  empíricamente: con `:Z` compila; con `--mount` falla. Requiere que el host
  tenga SELinux habilitado; en hosts sin SELinux el flag es inocuo.

- No hay límite de bytes de salida a nivel de kernel; el timeout y el tamaño del
  tmpfs acotan el daño (`ulimit -f` se aplica vía `--ulimit=fsize`).
- Si el runtime está comprometido o mal configurado (por ejemplo, user
  namespaces deshabilitados), el aislamiento es más débil. `rose doctor`
  reporta el modo y queda registrado en el manifiesto del trabajo.
- La verificación de symlinks y rutas de imágenes ocurre antes del montaje; el
  contenedor solo ve copias saneadas dentro de `/src`.

## Alternativas descartadas

1. **Compilar en el host con `-no-shell-escape`.** Insuficiente: no aísla
   lectura de archivos, procesos ni recursos. Prohibido.
2. **Compilar en el host dentro de `bwrap` sin auditar.** Aislamiento no
   verificado en esta máquina; se reevalúa con pruebas propias.
3. **Tectonic.** Sin instalar, sin verificar fuentes/licencias del branding.
