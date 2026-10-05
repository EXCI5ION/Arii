#!/bin/bash
#SBATCH --job-name=arii-pca-smoke
#SBATCH --partition=basico
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%j.log

set -eu

ARII_RUNTIME="$HOME/arii/runtime"
ARII_ENV="$ARII_RUNTIME/envs/arii-r-2026.08"
export MAMBA_ROOT_PREFIX="$ARII_RUNTIME/mamba"

cd -- "$SLURM_SUBMIT_DIR"
"$ARII_RUNTIME/bin/micromamba" run --prefix "$ARII_ENV" \
  Rscript pca_worker.R job.json result.json

test -s result.json
chmod 600 result.json
printf 'ARII_PCA_SMOKE_OK\n'
