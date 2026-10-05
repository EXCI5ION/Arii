#!/usr/bin/env bash
set -euo pipefail

VERSION="${ARII_VERSION:-1.0.0}"
INSTALL_BASE="${ARII_INSTALL_BASE:-$HOME/arii/runtime/releases}"
RELEASE_BASE_URL="${ARII_RELEASE_BASE_URL:-https://github.com/EXCI5ION/Arii/releases/download/v${VERSION}}"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
ARCHIVE_NAME="${ROOT_NAME}.tar.gz"
CHECKSUM_NAME="SHA256SUMS-cluster-${VERSION}.txt"
TARGET="$INSTALL_BASE/$ROOT_NAME"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "$VERSION" =~ ^[0-9]+[.][0-9]+[.][0-9]+([.-][A-Za-z0-9.-]+)?$ ]] \
  || fail "versión no válida: $VERSION"
[[ "$INSTALL_BASE" == /* && "$INSTALL_BASE" != "/" ]] \
  || fail "ARII_INSTALL_BASE debe ser una ruta absoluta distinta de /"
[[ "$(uname -s)" == "Linux" ]] || fail "este runtime requiere Linux"
[[ "$(uname -m)" == "x86_64" ]] || fail "este runtime requiere x86_64"

if command -v getconf >/dev/null 2>&1; then
  GLIBC_TEXT="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
  if [[ "$GLIBC_TEXT" =~ ([0-9]+[.][0-9]+) ]]; then
    GLIBC_VERSION="${BASH_REMATCH[1]}"
    OLDEST="$(printf '%s\n' "2.28" "$GLIBC_VERSION" | sort -V | head -n 1)"
    [[ "$OLDEST" == "2.28" ]] \
      || fail "se requiere glibc 2.28 o posterior; detectada $GLIBC_VERSION"
  fi
fi

if [[ -e "$TARGET" ]]; then
  if [[ -x "$TARGET/bin/Rscript" && -s "$TARGET/share/arii/runtime-manifest.json" ]]; then
    printf 'ARII_CLUSTER_RUNTIME_ALREADY_INSTALLED=%s\n' "$TARGET"
    exit 0
  fi
  fail "el destino existe pero no contiene una instalación completa: $TARGET"
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arii-server-install.XXXXXX")"
cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

download() {
  local url="$1"
  local destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --retry 3 --output "$destination" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --tries=3 --output-document="$destination" "$url"
  else
    fail "se necesita curl o wget para descargar el runtime"
  fi
}

printf 'Descargando Arii %s para servidor...\n' "$VERSION"
download "$RELEASE_BASE_URL/$ARCHIVE_NAME" "$WORK_DIR/$ARCHIVE_NAME"
download "$RELEASE_BASE_URL/$CHECKSUM_NAME" "$WORK_DIR/$CHECKSUM_NAME"

(
  cd "$WORK_DIR"
  sha256sum -c "$CHECKSUM_NAME"
)

ARCHIVE_ROOTS="$(tar -tzf "$WORK_DIR/$ARCHIVE_NAME" | cut -d/ -f1 | sort -u)"
[[ "$ARCHIVE_ROOTS" == "$ROOT_NAME" ]] \
  || fail "el archivo no contiene la raíz esperada: $ROOT_NAME"

mkdir -p "$INSTALL_BASE"
tar -xzf "$WORK_DIR/$ARCHIVE_NAME" -C "$INSTALL_BASE"
"$TARGET/install-runtime.sh"

cat <<EOF

Arii $VERSION quedó instalado en:
  $TARGET

Ruta que debe configurar en la aplicación de escritorio:
  $TARGET/bin/Rscript

Prueba opcional mediante Slurm:
  cd "$TARGET"
  sbatch share/arii/health.sbatch
EOF
