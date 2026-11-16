#!/bin/sh
# Prova de restore: restaura um dump num banco DESCARTAVEL no mesmo Postgres do CT 116,
# compara a contagem de linhas de cada tabela com o manifesto do backup, confere que os
# gatilhos append-only voltaram funcionando e apaga o banco descartavel. Nao toca no leia_lab.
# Uso (no host Proxmox): leia-pg-restore-test.sh [/var/backups/leia/leia_lab-AAAAMMDD-HHMMSS.dump]
set -eu

CT="${LEIA_CT:-116}"
DIR="${LEIA_BACKUP_DIR:-/var/backups/leia}"
DUMP="${1:-$(ls -1t "$DIR"/leia_lab-*.dump | head -1)}"
TMPDB="leia_restore_test_$(date +%s)"
PSQL="pct exec $CT -- docker exec -i leia-lab-postgres psql -U leia -v ON_ERROR_STOP=1"

sha256sum -c "$DUMP.sha256" >/dev/null
echo "dump: $DUMP (sha256 ok)"

cleanup() { $PSQL -d postgres -qc "DROP DATABASE IF EXISTS $TMPDB" >/dev/null 2>&1 || true; }
trap cleanup EXIT

$PSQL -d postgres -qc "CREATE DATABASE $TMPDB"
pct exec "$CT" -- docker exec -i leia-lab-postgres pg_restore -U leia -d "$TMPDB" --exit-on-error < "$DUMP"

$PSQL -d "$TMPDB" -At -c "
  select format('%s|%s', table_name,
    (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text)
  from information_schema.tables
  where table_schema = 'public' and table_type = 'BASE TABLE'
  order by table_name" > "/tmp/$TMPDB.counts"

if diff -u "$DUMP.counts" "/tmp/$TMPDB.counts" > "/tmp/$TMPDB.diff"; then
  echo "contagens: $(wc -l < "$DUMP.counts") tabelas identicas ao manifesto"
else
  echo "DIVERGENCIA entre manifesto e restore:"; cat "/tmp/$TMPDB.diff"; rm -f "/tmp/$TMPDB".*; exit 1
fi
rm -f "/tmp/$TMPDB".*

# O restore tem de trazer as protecoes, nao so os dados.
# TRUNCATE dispara o gatilho de comando mesmo com o historico vazio (DELETE so dispara por linha).
if $PSQL -d "$TMPDB" -qc "TRUNCATE domain_history" >/dev/null 2>&1; then
  echo "FALHA: TRUNCATE no historico foi aceito no banco restaurado"; exit 1
fi
echo "gatilho append-only: ativo no banco restaurado"
$PSQL -d "$TMPDB" -At -c "select 'leia_app pode editar risk_matrix: ' || has_table_privilege('leia_app', 'risk_matrix', 'UPDATE')"
echo "restore ok em $(date -Iseconds)"
