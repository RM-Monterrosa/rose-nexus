# ADR-006 — Stack web de H2 y alcance de la primera UI

- **Estado:** aceptado
- **Fecha:** 2026-11-15
- **Contexto:** H2 exige API, auth mínima, subida, trabajos, vista previa y
  exportación, usable desde PC y teléfono en la LAN. El motor de documentos ya
  existe y no debe ganar dependencias.

## Decisión

| Capa | Elección | Motivo |
|---|---|---|
| API | **FastAPI 0.163.1 + uvicorn 0.54.0** | El plan v0.2 ya lo propone; validación y OpenAPI sin escribir un router a mano. |
| Subidas | **python-multipart 0.0.33** | Requisito de FastAPI para `multipart/form-data`. |
| Persistencia | **SQLite** (`sqlite3`, stdlib) | Cero servicio extra, migraciones por `PRAGMA user_version`. |
| UI | **HTML server-rendered, CSS mobile-first, JS mínimo** | Sin toolchain Node, sin build, verificable con `urllib`. |
| Dependencias | Solo en `.venv` del proyecto, fijadas por versión | Nunca global; el motor de documentos sigue stdlib puro. |

`pyproject.toml` expone el extra `web` con las tres versiones exactas. Sin ese
extra, `rose` (CLI) y el motor siguen funcionando con biblioteca estándar.

## Por qué no SPA (React/Vite) en este incremento

El plan la lista como «opción inicial», no como requisito de H2. Una SPA suma
toolchain de Node, bundler, proxy de desarrollo y pruebas de DOM: mucho riesgo de
entrega para funciones que son formularios y listas. La UI server-rendered cubre
el criterio de cierre (subir desde el teléfono, ver progreso, descargar) y deja
React disponible para H2b **si** la interacción lo justifica. Se revisa con
mediciones, no por preferencia.

## Seguridad mínima exigida

- Contraseña con **`scrypt`** (n=2^14, r=8, p=1), sal por usuario, comparación en
  tiempo constante. Nunca se guarda la contraseña ni su hash en logs.
- Sesión: token aleatorio de 32 bytes; en la base se guarda **solo su SHA-256**.
  Cookie `HttpOnly`, `SameSite=Lax`, `Path=/` y `Secure` cuando el despliegue es
  HTTPS.
- **CSRF**: token por sesión, campo oculto en cada formulario, comparación en
  tiempo constante en todo POST.
- **Autorización por espacio**: toda consulta filtra por `user_id` y `space`;
  pedir un recurso ajeno devuelve 404, no 403 (no filtra existencia).
- Subidas: extensión en `{.md,.txt}`, límite de bytes, UTF-8 estricto, nombre de
  archivo solo como etiqueta saneada; el original se guarda por **hash**.
- Descargas: la ruta sale de la base, nunca del pedido del cliente.
- Cabeceras: `CSP default-src 'self'`, `nosniff`, `no-referrer`,
  `X-Frame-Options: DENY`.
- Fuerza bruta: límite de intentos por IP+usuario con ventana temporal.
- **LAN no es red confiable**: TLS queda a cargo del proxy del despliegue; la app
  no asume HTTPS y por eso no exige `Secure` en desarrollo.

## Fuera de alcance de H2

Registro público de usuarios, recuperación de contraseña por correo, OAuth,
multi-espacio con invitaciones, SPA, TLS integrado, `gh`/CI. Se documentan como
pendientes, no se simulan.
