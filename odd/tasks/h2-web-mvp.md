# Feature: H2 — Aplicación web MVP (API + UI responsive)

**Estado:** en curso · **Rama:** `feat/h2-web-mvp` · **Plan:** `docs/production-plan.md` (v0.2)

## Specs

- **S1** — «Entonces si, aprueba la imagen- Arranca el H2 y cuando todo este,
  publicalo». Alcance: cerrar la imagen TeX del sandbox (cierra H1), entregar H2
  y publicar rama y PR.
- **S2** — H2 del plan: «API, frontend, auth mínima, upload, jobs, preview,
  export.» Evidencia de cierre: «Demo en PC y teléfono LAN.»
- **S3** — M0 del plan: «Usuarios locales, autenticación y sesiones; autorización
  por espacio.» · «API y frontend responsive; subida controlada de archivos;
  biblioteca básica.» · «Almacenamiento de originales y resultados; metadatos en
  SQLite.» · «Cola de trabajos y eventos de progreso; logs por trabajo.»
- **S4** — Cierre de M0: «desde teléfono en la LAN, un usuario autorizado sube un
  `.md`, ve el trabajo y descarga el resultado; otro usuario sin permiso no puede
  acceder al archivo.»
- **S5** — Definition of Done: «Una persona autorizada puede, sin conocimientos
  de LaTeX, subir un `.md` desde su navegador y obtener un PDF correcto con la
  marca; también puede descargar el `.tex`; el sistema conserva el original,
  muestra errores de compilación comprensibles, no necesita LLM para convertir y
  no concede acceso arbitrario al servidor.»
- **S6** — Seguridad: «`LAN` no equivale a red confiable»; autenticación,
  «HTTPS/TLS cuando sea viable, CSRF/CORS y expiración de sesión». Nada de rutas
  arbitrarias ni acceso directo al filesystem por la UI.
- **S7** — «Utilizar código determinista para la conversión, no IA.» H2 reusa el
  motor de H1; el LLM sigue apagado.
- **S8** — «Publicar»: `push` de la rama y PR con descripción revisable.

## Decisión de alcance (ADR-006)

- Backend: **FastAPI + uvicorn** en `.venv` local (dependencias fijadas por
  versión). El motor de documentos sigue **sin dependencias**.
- UI: **server-rendered responsive** (HTML + CSS mobile-first, JS mínimo
  progresivo), sin toolchain de Node ni SPA en este incremento. React/Vite queda
  para H2b si la UI lo exige; se documenta el motivo.
- Persistencia: **SQLite** (stdlib `sqlite3`) con esquema versionado por
  migraciones idempotentes.

## Tasks

| ID | Spec | Entrega | Estado | Commit |
|---|---|---|---|---|
| T1 | S1 | Imagen TeX mínima, digest fijado, 11 fixtures a PDF real | ✅ | `9935ead` (rama H1) |
| T2 | S3, S6 | Esquema SQLite + repositorios con scoping por dueño | ✅ | `e131423` |
| T3 | S3, S6 | Auth local: `scrypt`, cookie firmada, CSRF, throttle | ✅ | `e131423` |
| T4 | S2, S3, S7 | API: subir, trabajo, estado, descargas, biblioteca | ✅ | `189ea1e` |
| T5 | S2, S6 | UI responsive: login, subida, biblioteca, detalle | ✅ | `189ea1e` |
| T6 | S4, S5, S6 | Pruebas: uvicorn real, aislamiento, CSRF, traversal | ✅ | `e131423` + `189ea1e` |
| T7 | S8 | `push` y PR encadenados | 🚧 | PR #1 abierto; PR #2 en curso |

## Slices

Dos commits de comportamiento en `feat/h2-web-mvp`, más uno de documentación.
El núcleo (`e131423`) y la capa HTTP (`189ea1e`) son revisables por separado: el
segundo no cambia ninguna regla del primero.

## Evidencia de verificación

- **201 pruebas** en verde (160 del motor + 41 de la capa web).
- **E2E manual 16/16** con uvicorn real: login, rechazo de CSRF, subida con hash
  estable, trabajo completado y **PDF real de 110.109 bytes** descargado con
  `Content-Disposition`, cabeceras de seguridad, 404 para recurso ajeno.

## Log

- **L1** (solicitud original, verbatim):

  > Entonces si, aprueba la imagen- Arranca el H2 y cuando todo este, publicalo

- **L2** — Entorno verificado: Node 24 / npm 11 presentes (no se usarán), `gh`
  ausente, `podman` rootless y `docker` 29.9.3 operativos, red a Debian OK.
- **L3** — **Bloqueo de publicación:** `git push --dry-run` falla con
  «Invalid username or token. Password authentication is not supported». No hay
  credencial de GitHub ni `gh`. Publicar requiere que el usuario configure un
  token/gh o abra el PR.
- **L4** — Desbloqueado: el usuario instaló y autenticó `gh` 2.97 (keyring,
  scopes `repo`+`workflow`). **PR #1 abierto y publicado**:
  https://github.com/RM-Monterrosa/rose-nexus/pull/1 (67 archivos, 6.444 líneas,
  base `main`). La contraseña de la cuenta no habilitaba Git: GitHub exige token
  u OAuth.
- **L5** — Verificación de H2: 201 pruebas en verde y E2E manual 16/16 con
  uvicorn real, incluyendo un **PDF real de 110.109 bytes** descargado por la API
  y cabeceras de seguridad en `/api/health`, `/login` y `/app`. Un fallo previo
  de la sonda era del propio verificador (normalización de mayúsculas de
  cabeceras), no del servidor.
