#!/usr/bin/env bash
# Build and verify the sandbox TeX image, then print a pinned reference.
#
# Usage: ./scripts/build-teximage.sh [image-tag]
# Honors ROSE_CONTAINER_RUNTIME (podman|docker); defaults to podman.
set -euo pipefail

cd "$(dirname "$0")/.."

RUNTIME="${ROSE_CONTAINER_RUNTIME:-podman}"
IMAGE="${1:-rose-nexus/texlive-sandbox:0.1.0}"
CONTEXT="deploy/sandbox/texlive"
REQUIRED_STYLES=(
  geometry.sty
  graphicx.sty
  array.sty
  longtable.sty
  xcolor.sty
  hyperref.sty
  fancyhdr.sty
)

command -v "$RUNTIME" >/dev/null || { echo "runtime '$RUNTIME' no disponible" >&2; exit 1; }
[ -f "$CONTEXT/Dockerfile" ] || { echo "falta $CONTEXT/Dockerfile" >&2; exit 1; }

echo "== build ($RUNTIME) =="
"$RUNTIME" build -t "$IMAGE" "$CONTEXT"

echo "== engine =="
"$RUNTIME" run --rm --network=none --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user 65534:65534 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  "$IMAGE" xelatex --version | head -2

echo "== required packages =="
for style in "${REQUIRED_STYLES[@]}"; do
  if "$RUNTIME" run --rm --network=none --read-only --cap-drop=ALL \
      --security-opt=no-new-privileges --user 65534:65534 \
      --tmpfs /tmp:rw,noexec,nosuid,size=64m \
      "$IMAGE" kpsewhich "$style" >/dev/null 2>&1; then
    echo "  ok   $style"
  else
    echo "  FALTA $style" >&2
    echo "missing TeX package in the image; add it to the Dockerfile" >&2
    exit 1
  fi
done

echo "== pinned references =="
IMAGE_ID="$("$RUNTIME" image inspect --format '{{.Id}}' "$IMAGE")"
IMAGE_DIGEST="$("$RUNTIME" image inspect --format '{{.Digest}}' "$IMAGE")"
NAME="${IMAGE%:*}"
if [ -z "$IMAGE_DIGEST" ] || [ "$IMAGE_DIGEST" = "<no value>" ]; then
  echo "  sin digest de repositorio: la imagen no está registrada por digest" >&2
  echo "  publicá la imagen en un registro o construí desde una referencia con digest" >&2
  exit 1
fi
PINNED="${NAME}@${IMAGE_DIGEST}"
echo "  image id : $IMAGE_ID"
echo "  digest   : $IMAGE_DIGEST"
echo "  pinned   : $PINNED"
if "$RUNTIME" run --rm --network=none --read-only --cap-drop=ALL \
    --security-opt=no-new-privileges --user 65534:65534 \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    "$PINNED" xelatex --version >/dev/null 2>&1; then
  echo "  PIN OK (el runtime acepta la referencia por digest local)"
  echo
  echo "Exportá: ROSE_SANDBOX_IMAGE=$PINNED"
else
  echo "  PIN RECHAZADO: el runtime no resuelve esa referencia" >&2
  echo "  Alternativa: publicar la imagen en un registro local y usar su RepoDigest." >&2
  exit 1
fi

REPO_DIGEST="$("$RUNTIME" image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || true)"
if [ -n "$REPO_DIGEST" ] && [ "$REPO_DIGEST" != "<no value>" ]; then
  echo "  repo digest: $REPO_DIGEST"
fi