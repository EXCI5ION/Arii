#!/usr/bin/env bash
#SBATCH --job-name=arii-runtime-install
#SBATCH --cpus-per-task=2
#SBATCH --mem=2048M
#SBATCH --time=02:00:00
#SBATCH --output=arii-runtime-install-%j.log

set -euo pipefail

ARII_ROOT="${ARII_ROOT:-$HOME/arii}"
VERSION="${ARII_VERSION:-1.0.0}"
RELEASE_DIR="${ARII_RELEASE_DIR:-$ARII_ROOT/releases}"
VALIDATION_DIR="${ARII_VALIDATION_DIR:-$ARII_ROOT/runtime/validation}"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
ARCHIVE="$RELEASE_DIR/${ROOT_NAME}.tar.gz"
RUNTIME_ROOT="$VALIDATION_DIR/$ROOT_NAME"

test -s "$ARCHIVE"
if [[ -e "$RUNTIME_ROOT" ]]; then
  printf 'ERROR: la ruta de validación ya existe: %s\n' "$RUNTIME_ROOT" >&2
  exit 30
fi

mkdir -p "$VALIDATION_DIR"
tar -xzf "$ARCHIVE" -C "$VALIDATION_DIR"
"$RUNTIME_ROOT/install-runtime.sh"

printf 'ARII_RUNTIME_CLEAN_INSTALL_OK=%s\n' "$RUNTIME_ROOT"
