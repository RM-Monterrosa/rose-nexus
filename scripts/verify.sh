#!/usr/bin/env bash
# Reproducible verification for H0/H1. Uses only the Python standard library.
# Usage: ./scripts/verify.sh [additional unittest args]
set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}backend"

echo "== doctor =="
python3 -m rose_nexus.cli doctor || true

echo
echo "== unittest =="
python3 -m unittest discover -s tests -t . -v "$@"
