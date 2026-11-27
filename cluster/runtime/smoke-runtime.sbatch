#!/usr/bin/env bash
#SBATCH --job-name=arii-runtime-pca
#SBATCH --cpus-per-task=2
#SBATCH --mem=2048M
#SBATCH --time=00:15:00
#SBATCH --output=arii-runtime-pca-%j.log

set -euo pipefail

ARII_ROOT="${ARII_ROOT:-$HOME/arii}"
VERSION="${ARII_VERSION:-1.1.0}"
RELEASE_DIR="${ARII_RELEASE_DIR:-$ARII_ROOT/releases}"
SUBMIT_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
SMOKE_PAYLOAD="${ARII_SMOKE_PAYLOAD:-$SUBMIT_DIR/smoke}"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
ARCHIVE="$RELEASE_DIR/${ROOT_NAME}.tar.gz"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/arii-runtime-smoke.XXXXXX")"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

test -s "$ARCHIVE"
test -s "$SMOKE_PAYLOAD/pca_worker.R"
test -s "$SMOKE_PAYLOAD/plsda_worker.R"
test -s "$SMOKE_PAYLOAD/pls_engine.R"
test -s "$SMOKE_PAYLOAD/dataset.csv"
test -s "$SMOKE_PAYLOAD/job.json"
test -s "$SMOKE_PAYLOAD/pls-job.json"

tar -xzf "$ARCHIVE" -C "$WORK_DIR"
RUNTIME_ROOT="$WORK_DIR/$ROOT_NAME"
"$RUNTIME_ROOT/install-runtime.sh"

mkdir -p "$WORK_DIR/job"
cp "$SMOKE_PAYLOAD/pca_worker.R" "$WORK_DIR/job/pca_worker.R"
cp "$SMOKE_PAYLOAD/plsda_worker.R" "$WORK_DIR/job/plsda_worker.R"
cp "$SMOKE_PAYLOAD/pls_engine.R" "$WORK_DIR/job/pls_engine.R"
cp "$SMOKE_PAYLOAD/dataset.csv" "$WORK_DIR/job/dataset.csv"
cp "$SMOKE_PAYLOAD/job.json" "$WORK_DIR/job/job.json"
cp "$SMOKE_PAYLOAD/pls-job.json" "$WORK_DIR/job/pls-job.json"

cd "$WORK_DIR/job"
"$RUNTIME_ROOT/bin/Rscript" pca_worker.R job.json result.json
test -s result.json
"$RUNTIME_ROOT/bin/Rscript" -e \
  'x <- jsonlite::fromJSON("result.json"); stopifnot(x$method == "pca", x$engine$name == "mixOmics", nrow(x$scores) == 7)'

"$RUNTIME_ROOT/bin/Rscript" plsda_worker.R pls-job.json pls-result.json
test -s pls-result.json
"$RUNTIME_ROOT/bin/Rscript" -e \
  'x <- jsonlite::fromJSON("pls-result.json"); stopifnot(x$method == "plsda", x$engine$name == "SIMPLS", grepl("^pls ", x$engine$version), x$performance$engine == "simpls")'

RESULT="$RELEASE_DIR/arii-runtime-pca-smoke-${SLURM_JOB_ID}.json"
install -m 600 result.json "$RESULT"
PLS_RESULT="$RELEASE_DIR/arii-runtime-simpls-smoke-${SLURM_JOB_ID}.json"
install -m 600 pls-result.json "$PLS_RESULT"
printf 'ARII_RUNTIME_PCA_SMOKE_OK=%s\n' "$RESULT"
printf 'ARII_RUNTIME_SIMPLS_SMOKE_OK=%s\n' "$PLS_RESULT"
