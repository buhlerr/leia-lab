#!/bin/sh
# Backup diario do Postgres da Leia (CT 116), rodado NO HOST PROXMOX (fora do CT).
# Guarda um dump custom (-Fc) do banco inteiro (Leia + Directus, que compartilham o banco)
# e um manifesto com a contagem de linhas por tabela, usado pela prova de restore.
set -eu

CT="${LEIA_CT:-116}"
DB="${LEIA_DB:-leia_lab}"
DIR="${LEIA_BACKUP_DIR:-/var/backups/leia}"
KEEP="${LEIA_BACKUP_KEEP:-14}"
TS="$(date +%Y%m%d-%H%M%S)"

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"
OUT="$DIR/$DB-$TS.dump"

pct exec "$CT" -- docker exec leia-lab-postgres pg_dump -U leia -d "$DB" -Fc > "$OUT.part"
mv "$OUT.part" "$OUT"

# Contagem por tabela logo apos o dump (o banco tem pouca escrita; a prova de restore aponta divergencias).
pct exec "$CT" -- docker exec leia-lab-postgres psql -U leia -d "$DB" -At -c "
  select format('%s|%s', table_name,
    (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text)
  from information_schema.tables
  where table_schema = 'public' and table_type = 'BASE TABLE'
  order by table_name" > "$OUT.counts"

sha256sum "$OUT" > "$OUT.sha256"

# Retencao: mantem os KEEP dumps mais recentes (e seus arquivos auxiliares).
ls -1t "$DIR/$DB"-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f "$old" "$old.counts" "$old.sha256"
done

echo "backup ok: $OUT ($(du -h "$OUT" | cut -f1), $(wc -l < "$OUT.counts") tabelas)"
