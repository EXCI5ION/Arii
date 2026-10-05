#!/usr/bin/env bash
#SBATCH --job-name=arii-pack-runtime
#SBATCH --cpus-per-task=8
#SBATCH --mem=4096M
#SBATCH --time=01:00:00
#SBATCH --output=arii-pack-runtime-%j.log

set -euo pipefail

ARII_ROOT="${ARII_ROOT:-$HOME/arii}"
VERSION="${ARII_VERSION:-1.0.0}"
SOURCE_ENV="${ARII_SOURCE_ENV:-$ARII_ROOT/runtime/envs/arii-r-2026.08}"
CONDA_PACK="${ARII_CONDA_PACK:-$ARII_ROOT/runtime/tools/conda-pack-0.8.1/bin/conda-pack}"
SUBMIT_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
PAYLOAD="${ARII_PAYLOAD_DIR:-$SUBMIT_DIR/payload}"
RELEASE_DIR="${ARII_RELEASE_DIR:-$ARII_ROOT/releases}"
ARCHIVE_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64.tar.gz"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arii-runtime-build.XXXXXX")"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

test -x "$SOURCE_ENV/bin/Rscript"
test -x "$CONDA_PACK"
test -s "$PAYLOAD/README-SERVER.md"
test -s "$PAYLOAD/install-runtime.sh"
test -s "$PAYLOAD/health.sbatch"
test -s "$PAYLOAD/health.R"
test -s "$PAYLOAD/runtime_manifest.R"
test -s "$PAYLOAD/explicit-lock.txt"

mkdir -p "$RELEASE_DIR" "$WORK_DIR/stage"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
STAGED_RUNTIME="$WORK_DIR/stage/$ROOT_NAME"

"$CONDA_PACK" --prefix "$SOURCE_ENV" --output "$STAGED_RUNTIME" \
  --format no-archive --n-threads "${SLURM_CPUS_PER_TASK:-1}"

# El historial de Conda registra la línea de comandos original, incluida la ruta
# privada del usuario que creó el entorno. El lock exportado también lleva esa
# ruta en su encabezado; las URLs y hashes reproducibles permanecen intactos.
sed -i '/^# cmd:/d' "$STAGED_RUNTIME/conda-meta/history"

mkdir -p "$STAGED_RUNTIME/share/arii"
install -m 755 "$PAYLOAD/install-runtime.sh" "$STAGED_RUNTIME/install-runtime.sh"
install -m 644 "$PAYLOAD/README-SERVER.md" "$STAGED_RUNTIME/README-SERVER.md"
install -m 644 "$PAYLOAD/health.sbatch" "$STAGED_RUNTIME/share/arii/health.sbatch"
install -m 644 "$PAYLOAD/health.R" "$STAGED_RUNTIME/share/arii/health.R"
sed '/^List of packages in environment:/d' "$PAYLOAD/explicit-lock.txt" \
  > "$STAGED_RUNTIME/share/arii/explicit-lock.txt"
chmod 644 "$STAGED_RUNTIME/share/arii/explicit-lock.txt"
install -m 644 "$PAYLOAD/LICENSE" "$STAGED_RUNTIME/share/arii/LICENSE"
install -m 644 "$PAYLOAD/THIRD_PARTY_NOTICES.md" \
  "$STAGED_RUNTIME/share/arii/THIRD_PARTY_NOTICES.md"

"$SOURCE_ENV/bin/Rscript" "$PAYLOAD/runtime_manifest.R" \
  "$STAGED_RUNTIME/share/arii/runtime-manifest.json"

if grep -R -a -l -F "$HOME" "$STAGED_RUNTIME" > "$WORK_DIR/personal-paths.txt"; then
  printf 'ERROR: el runtime conserva rutas del directorio personal:\n' >&2
  cat "$WORK_DIR/personal-paths.txt" >&2
  exit 40
fi

OUTPUT_PART="$RELEASE_DIR/$ARCHIVE_NAME.part"
OUTPUT="$RELEASE_DIR/$ARCHIVE_NAME"
tar --numeric-owner --owner=0 --group=0 -czf "$OUTPUT_PART" \
  -C "$WORK_DIR/stage" "$ROOT_NAME"
mv -f -- "$OUTPUT_PART" "$OUTPUT"
(
  cd "$RELEASE_DIR"
  sha256sum "$ARCHIVE_NAME" > "SHA256SUMS-cluster-${VERSION}.txt"
)

printf 'ARII_CLUSTER_RUNTIME_ARCHIVE=%s\n' "$OUTPUT"
du -h "$OUTPUT"
