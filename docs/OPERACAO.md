# Operação da Leia (M6)

Como o que está em produção no homelab é protegido, restaurado e vigiado. Acesso ao CT 116: pelo host
Proxmox (`pve`, 192.168.0.9) com `pct exec 116`. **Não use SSH direto em 192.168.0.120**: outro
aparelho na rede já respondeu por esse IP (conflito de ARP, ver bead `leia-lab-1g1.10`).

## Backup e restore do Postgres

| O quê | Onde |
|---|---|
| Script de backup | `deploy/backup/leia-pg-backup.sh` → instalado em `/usr/local/sbin/` no **pve** |
| Agendamento | `leia-pg-backup.timer` (systemd no pve): todo dia às 03:15, `Persistent=true` |
| Destino | `/var/backups/leia/` no pve (fora do CT, `chmod 700`), **14 cópias** |
| Conteúdo | `pg_dump -Fc` do banco `leia_lab` inteiro (Leia **e** Directus, que dividem o banco) + `.counts` (linhas por tabela) + `.sha256` |
| Prova de restore | `deploy/backup/leia-pg-restore-test.sh` (instalado ao lado) |

A prova de restore restaura o dump mais recente num banco **descartável** no mesmo Postgres, compara a
contagem de cada tabela com o manifesto, confere que o gatilho append-only voltou (o `TRUNCATE` no
histórico tem de falhar) e apaga o banco descartável. O `leia_lab` não é tocado.

```bash
ssh root@192.168.0.9 /usr/local/sbin/leia-pg-restore-test.sh          # dump mais recente
ssh root@192.168.0.9 journalctl -u leia-pg-backup.service -n 20        # últimos backups
```

**Último restore testado: 2026-11-15 23:02 (-03)**, dump `leia_lab-20261115-230220.dump`: 52 tabelas
idênticas ao manifesto, gatilho append-only ativo. Também conferido que um manifesto adulterado
(`risk_matrix` 999 contra 6) faz o teste falhar.

Limite conhecido: o backup fica no mesmo host físico do CT. Se o `pve` morrer, os dois somem. Uma
cópia fora do homelab é decisão pendente.

## Rastreio (LangSmith): quem vê o quê

- **O que vai para a LangSmith:** só conteúdo mascarado (o grafo nunca vê texto cru) e o apelido
  `documento-…` do arquivo. Chaves e `DATABASE_URL` nunca entram: os spans dos clientes registram só
  os argumentos permitidos (`src/tracing.py`). Isso é provado em `tests/test_tracing.py`.
- **Quando:** só com `--trace` no CLI. **Não defina `LANGSMITH_TRACING=true` no ambiente**: o SDK
  passaria a rastrear toda execução.
- **Quem vê:** os membros do workspace da LangSmith (hoje, só o dono da conta). Ao convidar alguém, a
  pessoa vê **todos** os traços do projeto `leia-lab`.
- **Links públicos:** não compartilhe traços por link público (`share_run`). Um traço tem o texto
  mascarado da minuta inteira, e o mascaramento é heurístico (nome de quem não aparece depois de um
  rótulo como "LOCADOR:" pode escapar).
- **Retenção:** no plano gratuito os traços expiram sozinhos (14 dias segundo a ADR-0002; confira no
  painel da conta). A auditoria **não** depende deles: ela está em `analysis_trail` no Postgres.
- **Apagar:** apagar o projeto `leia-lab` na LangSmith remove todos os traços de uma vez.

## Limite do plano

```bash
uv run python -m src.cli trace-usage            # [ok] 3/5000 tracos em leia-lab desde 2026-11-01
uv run python -m src.cli trace-usage --limit 5000 --warn 0.8   # sai com código 2 a partir de 80%
```

Conta os traços raiz (1 por análise) do projeto no mês. O limite vale para a **organização**: se
houver outros projetos, o número é um piso. A conferência final é o painel de billing (bead
`leia-lab-8tr.9`). `list_runs` do SDK sai depois de 31/01/2027: migrar para `client.runs.query()`.

## Pendente

- **HTTPS do admin pelo Pangolin:** o token em `mcp-pangolin/.env` respondeu 401. É preciso um token
  válido e o subdomínio desejado. Até lá o admin é HTTP só na LAN (`http://192.168.0.120:8000`).
