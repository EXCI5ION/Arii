#!/usr/bin/env bash
#SBATCH --job-name=arii-runtime-health
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M
#SBATCH --time=00:05:00
#SBATCH --output=arii-runtime-health-%j.log

set -euo pipefail

RUNTIME_ROOT="${ARII_RUNTIME_DIR:-$SLURM_SUBMIT_DIR}"
RESULT="$SLURM_SUBMIT_DIR/arii-runtime-health-${SLURM_JOB_ID}.json"

"$RUNTIME_ROOT/bin/Rscript" "$RUNTIME_ROOT/share/arii/health.R" > "$RESULT"
grep -q '"status": "ok"' "$RESULT"
chmod 600 "$RESULT"
printf 'ARII_CLUSTER_RUNTIME_SLURM_OK=%s\n' "$RUNTIME_ROOT"
