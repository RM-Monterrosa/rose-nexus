# Rose Nexus

Plataforma personal y local para transformar documentos, estudiar y mover
información entre dispositivos, con IA local opcional. El plan técnico vive en
[`docs/production-plan.md`](docs/production-plan.md).

**Estado actual:** H0 (baseline verificado) y H1 (convertidor CLI determinista
`.md`/`.txt` → `.tex` → `.pdf`). El PDF requiere una imagen TeX fijada por digest
(`ROSE_SANDBOX_IMAGE`); sin ella el flujo `.tex` sigue funcionando y el PDF se
rechaza con exit 4. No hay MCP, OCR, ASR, multiagentes ni frontend.

## Qué funciona hoy

- Parser determinista de un subconjunto documentado de Markdown y de texto plano.
- Generación de LaTeX con escape estricto, sin LaTeX crudo del usuario.
- Perfil de branding versionado (`demo`, explícitamente **provisional**).
- Artefactos por trabajo: original, `.tex`, assets y `manifest.json` con SHA-256.
- Política de seguridad LaTeX y compilador en contenedor endurecido.
- CLI `rose convert`, `rose brands`, `rose doctor`.

**La salida PDF** está habilitada cuando existe una imagen TeX fijada por digest:

```bash
./scripts/build-teximage.sh                      # construye y verifica la imagen
podman image inspect rose-nexus/texlive-sandbox:0.1.0 --format '{{.Digest}}'
export ROSE_SANDBOX_IMAGE="rose-nexus/texlive-sandbox@sha256:<digest>"
```

Sin imagen aprovisionada, `rose convert --format pdf` falla con `sandbox_unavailable`
(exit 4) **antes** de escribir artefactos. Nunca se compila en el host.

## Requisitos

- Python 3.11+ (probado con 3.15.2). Cero dependencias de terceros.
- Docker o Podman, solo para la ruta PDF.

## Uso

```bash
# Sin instalar nada
PYTHONPATH=backend python3 -m rose_nexus.cli doctor
PYTHONPATH=backend python3 -m rose_nexus.cli brands
PYTHONPATH=backend python3 -m rose_nexus.cli convert tests/fixtures/markdown/01-headings.md \
  --out build            # identidad canónica: invering
PYTHONPATH=backend python3 -m rose_nexus.cli convert tests/fixtures/markdown/01-headings.md \
  --brand demo --out build   # perfil PROVISIONAL rosa/azul
```

Instalación local opcional (entorno virtual, nunca global):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
rose convert documento.md --out build
rose convert documento.md --brand demo --out build   # provisional
```

## Verificación

```bash
./scripts/verify.sh
```

## Seguridad

- LaTeX generado se valida antes de compilar (sin `shell-escape`, sin rutas
  arbitrarias, paquetes de una lista blanca).
- La compilación exige contenedor sin red, rootfs de solo lectura, usuario no
  root y límites de recursos.
- Los documentos de usuario son datos, nunca instrucciones.

Ver `AGENTS.md`, `docs/architecture.md` y `docs/threat-model.md`.

## Reglas de privacidad

- Los archivos originales son inmutables y cada salida registra su procedencia.
- Espacios `personal`, `academico` y `empresa` se separan lógicamente; no se
  mezclan sin autorización explícita.
- La inferencia local (fase posterior) escucha solo en `127.0.0.1`.
