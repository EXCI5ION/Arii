#!/usr/bin/env bash
#SBATCH --job-name=arii-pack-tools
#SBATCH --cpus-per-task=1
#SBATCH --mem=1024M
#SBATCH --time=00:30:00
#SBATCH --output=arii-pack-tools-%j.log

set -euo pipefail

ARII_ROOT="${ARII_ROOT:-$HOME/arii}"
MICROMAMBA="$ARII_ROOT/runtime/bin/micromamba"
TOOLS_ENV="$ARII_ROOT/runtime/tools/conda-pack-0.8.1"
export MAMBA_ROOT_PREFIX="$ARII_ROOT/runtime/mamba"

"$MICROMAMBA" create -y --prefix "$TOOLS_ENV" \
  --channel conda-forge --strict-channel-priority \
  python=3.12 conda-pack=0.8.1 setuptools=80.9.0

"$TOOLS_ENV/bin/conda-pack" --version
printf 'ARII_CONDA_PACK_READY=%s\n' "$TOOLS_ENV/bin/conda-pack"
