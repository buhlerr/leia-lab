#!/usr/bin/env bash
# Sincroniza o Beads com o Linear so quando algo mudou (detalhes em scripts/linear_sync.py).
# Uso, da raiz do repo:  op run --env-file=.env.op -- scripts/linear-sync.sh [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -I scripts/linear_sync.py "$@"
