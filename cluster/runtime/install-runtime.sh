#!/usr/bin/env bash
set -euo pipefail

RUNTIME_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [[ ! -x "$RUNTIME_ROOT/bin/conda-unpack" ]]; then
  printf 'ERROR: no se encontró bin/conda-unpack en %s\n' "$RUNTIME_ROOT" >&2
  exit 1
fi

"$RUNTIME_ROOT/bin/conda-unpack"
"$RUNTIME_ROOT/bin/Rscript" "$RUNTIME_ROOT/share/arii/health.R"
printf '\nARII_CLUSTER_RUNTIME_READY=%s\n' "$RUNTIME_ROOT"
