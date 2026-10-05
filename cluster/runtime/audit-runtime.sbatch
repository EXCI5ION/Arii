#!/usr/bin/env bash
#SBATCH --job-name=arii-runtime-audit
#SBATCH --cpus-per-task=1
#SBATCH --mem=512M
#SBATCH --time=00:10:00
#SBATCH --output=arii-runtime-audit-%j.log

set -euo pipefail

ARII_ROOT="${ARII_ROOT:-$HOME/arii}"
VERSION="${ARII_VERSION:-1.0.0}"
RELEASE_DIR="${ARII_RELEASE_DIR:-$ARII_ROOT/releases}"
ROOT_NAME="Arii-${VERSION}-cluster-runtime-linux-x86_64"
ARCHIVE="$RELEASE_DIR/${ROOT_NAME}.tar.gz"
LIST="$RELEASE_DIR/arii-runtime-archive-list.txt"
VERBOSE_LIST="$RELEASE_DIR/arii-runtime-archive-verbose.txt"
DENY_REGEX="${ARII_AUDIT_DENY_REGEX:-(^|/)[.]ssh(/|$)|(^|/)jobs(/|$)|authorized_keys|known_hosts|id_(rsa|ed25519)|(^|/)credentials([.][^/]*)?($|/)}"

test -s "$ARCHIVE"
tar -tzf "$ARCHIVE" > "$LIST"
tar -tvzf "$ARCHIVE" > "$VERBOSE_LIST"

test "$(cut -d/ -f1 "$LIST" | sort -u | wc -l)" -eq 1
test "$(cut -d/ -f1 "$LIST" | sort -u)" = "$ROOT_NAME"

if grep -E -i "$DENY_REGEX" "$LIST"; then
  printf 'ERROR: el archivo contiene un nombre potencialmente sensible\n' >&2
  exit 20
fi

if grep -Ev '^[^ ]+ +0/0 +' "$VERBOSE_LIST" | grep -q .; then
  printf 'ERROR: el archivo contiene propietarios no neutros\n' >&2
  exit 21
fi

MANIFEST="$(tar -xOzf "$ARCHIVE" \
  "$ROOT_NAME/share/arii/runtime-manifest.json")"
if printf '%s' "$MANIFEST" | grep -E -i \
  "$DENY_REGEX|/home/|/Users/|[.]ssh"; then
  printf 'ERROR: el manifiesto contiene una ruta o identidad sensible\n' >&2
  exit 22
fi

printf 'ARII_RUNTIME_AUDIT_OK\n'
