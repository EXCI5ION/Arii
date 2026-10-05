#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VERSION="1.0.0"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
ARCHIVE_NAME="${ROOT_NAME}.tar.gz"
CHECKSUM_NAME="SHA256SUMS-cluster-${VERSION}.txt"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arii-install-test.XXXXXX")"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

RELEASE_DIR="$WORK_DIR/release/v${VERSION}"
STAGE_DIR="$WORK_DIR/stage/$ROOT_NAME"
INSTALL_BASE="$WORK_DIR/installed"
mkdir -p "$RELEASE_DIR" "$STAGE_DIR/bin" "$STAGE_DIR/share/arii"

cat > "$STAGE_DIR/install-runtime.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
touch "$ROOT/installation-ok"
EOF
chmod 755 "$STAGE_DIR/install-runtime.sh"

cat > "$STAGE_DIR/bin/Rscript" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod 755 "$STAGE_DIR/bin/Rscript"
printf '{}\n' > "$STAGE_DIR/share/arii/runtime-manifest.json"

tar -czf "$RELEASE_DIR/$ARCHIVE_NAME" -C "$WORK_DIR/stage" "$ROOT_NAME"
(
  cd "$RELEASE_DIR"
  sha256sum "$ARCHIVE_NAME" > "$CHECKSUM_NAME"
)

ARII_VERSION="$VERSION" \
ARII_INSTALL_BASE="$INSTALL_BASE" \
ARII_RELEASE_BASE_URL="file://$RELEASE_DIR" \
  bash "$PROJECT_ROOT/cluster/install-server.sh"

test -x "$INSTALL_BASE/$ROOT_NAME/bin/Rscript"
test -s "$INSTALL_BASE/$ROOT_NAME/share/arii/runtime-manifest.json"
test -f "$INSTALL_BASE/$ROOT_NAME/installation-ok"

# Una segunda ejecución debe detectar la instalación completa sin sobrescribirla.
ARII_VERSION="$VERSION" \
ARII_INSTALL_BASE="$INSTALL_BASE" \
ARII_RELEASE_BASE_URL="file://$RELEASE_DIR" \
  bash "$PROJECT_ROOT/cluster/install-server.sh"

printf 'ARII_SERVER_INSTALLER_TEST_OK\n'
