#!/usr/bin/env bash
# Sincroniza o Beads com o Linear (time VIT) nos dois sentidos, sem levar o historico fechado.
# Uso, da raiz do repo:  op run --env-file=.env.op -- scripts/linear-sync.sh [--dry-run]
set -euo pipefail

cd "$(dirname "$0")/.."
BD=$(command -v bd-go || command -v bd)

# 1. Linear -> Beads: tudo, para que fechar ou reabrir no Linear chegue aqui.
"$BD" linear sync --pull "$@"

# 2. Beads -> Linear: so as abertas; as 62 fechadas antes do espelho ficam fora.
"$BD" linear sync --push --state open "$@"

# 3. Fechadas que ja estao no Linear: vao para Done la.
closed=$("$BD" list --status closed --json | python3 -I -c '
import json, sys
print(",".join(i["id"] for i in json.load(sys.stdin) if "linear.app" in (i.get("external_ref") or "")))')
if [ -n "$closed" ]; then
  "$BD" linear sync --push --issues "$closed" "$@"
fi

# 4. Projeto: toda issue deste repo fica no projeto leia-lab do Linear (o bd nao sabe de projetos).
"$BD" list --all --json | python3 -I scripts/linear_project.py leia-lab "$@"
