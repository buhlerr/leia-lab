# Operação da Leia (M6)

Como o que está em produção no homelab é protegido, restaurado e vigiado. Acesso ao CT 116: pelo host
Proxmox (`pve`, 192.168.0.9) com `pct exec 116`. **Não use SSH direto em 192.168.0.120**: outro
aparelho na rede já respondeu por esse IP (conflito de ARP, ver bead `leia-lab-1g1.10`).

## Acesso público: Cloudflare Tunnel (migrado do Pangolin em 2026-11-23)

Em 2026-11-23 a VPS Oracle do Pangolin (`137.131.254.251`) parou de responder em 80/443 (TCP aceita,
TLS trava). `admin`, `leia-api` e `mlflow` saíram do Pangolin e passaram para um Cloudflare Tunnel. Os
demais subdomínios ainda caem no wildcard `*.rauvbr.com` → Oracle.

| Peça | Estado (2026-11-23) |
|---|---|
| Túnel | `homelab` (id `50694789-7da4-40e4-ab31-27ac2c5f88e3`), gerenciado pelo painel/API da Cloudflare (conta "Vitor Account") |
| Conector | `cloudflared` no **CT 103** (`192.168.0.128`, o mesmo do Newt), serviço systemd `cloudflared`, token em `/etc/cloudflared/tunnel.env` (chmod 600) |
| Rotas (ingress) | `admin.rauvbr.com` → `http://192.168.0.120:8000`, `leia-api.rauvbr.com` → `:8080`, `mlflow.rauvbr.com` → `:5000`; o resto → 404 |
| DNS | CNAME proxied de cada nome para `50694789-7da4-40e4-ab31-27ac2c5f88e3.cfargotunnel.com`; ganham do wildcard |
| Login | **Cloudflare Access** (org `vbrrau.cloudflareaccess.com`, código por e-mail) em `admin` e `mlflow`, aplicações `leia admin` e `leia mlflow`, política `donos`. `leia-api` sem Access: a barreira é o bearer |
| Portas 8000/8080 na LAN | **fechadas**: só os conectores (host pve `192.168.0.9` e CT 103 `192.168.0.128`) passam. Firewall `leia-admin-firewall.service` no CT 116 (cadeia `LEIA-ADMIN` em `DOCKER-USER`, reaplicada no boot) |
| Django | `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` com `admin.rauvbr.com`; `DJANGO_BEHIND_HTTPS_PROXY=true` |

Quem pode entrar no admin e no mlflow é decidido no Cloudflare Access (Zero Trust → Access →
Applications → política `donos`), antes do login do Django. Para incluir uma pessoa: adicione o e-mail na
política **e** crie o usuário no Django nos grupos `editor` ou `leitor`.

Estado do túnel: `ssh pve "pct exec 103 -- systemctl status cloudflared"` e
`journalctl -u cloudflared` no CT 103. Se o conector mudar de máquina, atualize os IPs em
`/usr/local/sbin/leia-admin-firewall.sh` no CT 116 e rode `systemctl restart leia-admin-firewall`.

O Newt e o Pangolin continuam instalados para os outros serviços; a chave `PANGOLIN_API_KEY` do Shelve só
vale para eles.

## API para a camada FE: https://leia-api.rauvbr.com

| Peça | Estado (2026-11-21) |
|---|---|
| Endereço | **https://leia-api.rauvbr.com** (Cloudflare Tunnel `homelab`), SSL, **sem Access**: a barreira é o bearer `LEIA_API_TOKEN` (o FE chama do servidor dele) |
| Caminho | Cloudflare → túnel `homelab` (cloudflared no CT 103) → `192.168.0.120:8080` (CT 116) |
| Serviço | `api` no `/root/leia/docker-compose.yml` (container `leia-api`, imagem `leia-api:<sha>`, build de `/root/leia/api`, separado do `management/` do admin), `entrypoint: python -m src.api`, healthcheck em `/healthz` |
| Segredos | `/root/leia/api.env` (chmod 600): `DATABASE_URL` do login `api_login` (membro de `leia_app`, não dono) e `LEIA_API_TOKEN` (64 hex). Gerados no próprio CT, nunca impressos |
| Porta 8080 na LAN | **fechada**: mesma cadeia `LEIA-ADMIN` da 8000 (`deploy/firewall/`) |
| Modelos | OpenRouter e TypeSafe em modo offline até as chaves entrarem (`leia-lab-8tr.9`); quando entrarem, vão no `api.env` |

Passar o token ao FE: `ssh root@192.168.0.9 pct exec 116 -- grep LEIA_API_TOKEN /root/leia/api.env`. Para
trocar o token, edite o `api.env` e rode `docker compose up -d --no-deps api`.

Atualizar a API para um commit novo (o admin não é tocado):

```bash
git archive --format=tar.gz -o leia-api-<sha>.tar.gz <sha> pyproject.toml uv.lock src deploy .dockerignore
# no CT 116, em /root/leia: mv api api.bak-<data>; mkdir api; tar -xzf leia-api-<sha>.tar.gz -C api
# troque a tag em image: leia-api:<sha> no compose, então:
docker compose build api && docker compose up -d --no-deps api
```

## Segredos (Shelve)

`shelve.json` na raiz aponta para o time `vitor`, projeto `LEIA` (padrão `development`; `production`
protegido contra push). Os segredos entram só no processo filho, sem `.env` em disco:

```bash
shelve run --env production -- uv run python -m src.cli gold-run --label real-v1 --trace
```

| No Shelve | Fora dele |
|---|---|
| `PANGOLIN_API_KEY`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | `SHELVE_TOKEN` e `LEIA_HOMELAB_PG_PASSWORD` / `LEIA_HOMELAB_DIRECTUS_PASSWORD` (variáveis de usuário do Windows) |

- Rode pelo **Git Bash**: o PowerShell remove o `--` antes de repassar a comandos nativos, e o
  `shelve run` passa a tratar o nome do ambiente como o programa ("Failed to start child process").
- **Não use `shelve pull`** em sessão de agente (grava os segredos em claro no disco).
- Faltam `TYPESAFE_API_KEY` e `OPENROUTER_API_KEY` (bead `leia-lab-8tr.9`): cadastre pelo app.

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

Cópia fora do homelab: decidido (2026-11-16) que vem do backup do Proxmox guardado na VPS do
usuário, configurado por ele. O dump diário daqui fica no pve; o backup do pve leva `/var/backups/leia`
junto se o job incluir o host, ou o CT 116 inteiro via vzdump.

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

## Rastreio da API: MLflow self-hosted

A API grava um trace MLflow por análise quando o `api.env` define `MLFLOW_TRACKING_URI`
(`http://leia-mlflow:5000`). Sem a variável, nada sai da API. O trace é marcado com
`leia.analysis_id` e o detalhe da análise no admin linka o trace no MLflow.

- **O que vai:** só conteúdo mascarado, a mesma política do `--trace` do CLI. A LangSmith fica
  fora da API.
- **Quem vê:** quem alcança o MLflow interno (`LEIA_MLFLOW_PUBLIC_URL`, hoje
  https://mlflow.rauvbr.com).
- **Admin:** a página **Nova análise** envia o arquivo pelo servidor à API
  (`LEIA_API_URL`/`LEIA_API_TOKEN` no `django.env`). O link do trace precisa de `LEIA_MLFLOW_URL`
  no `django.env`; sem ela o detalhe mostra "sem trace".
- **Apagar:** os traces ficam no MLflow do homelab; apagar o experimento `leia-lab` remove todos.
  A auditoria segue no Postgres (`analysis_trail`).

## Limite do plano

```bash
uv run python -m src.cli trace-usage            # [ok] 3/5000 tracos em leia-lab desde 2026-11-01
uv run python -m src.cli trace-usage --limit 5000 --warn 0.8   # sai com código 2 a partir de 80%
```

Conta os traços raiz (1 por análise) do projeto no mês. O limite vale para a **organização**: se
houver outros projetos, o número é um piso. A conferência final no painel de billing foi fechada em
2026-11-16 (`leia-lab-etv`): 10 traços faturáveis no mês em `Workspace 1` (3 em 13/11 e 7 em 16/11),
confirmando 1 unidade por análise sem cobrança de sub-runs. `list_runs` do SDK sai depois de
31/01/2027: migrar para `client.runs.query()`.

## Pendente

- Ligar `DJANGO_BEHIND_HTTPS_PROXY=true` no `django.env` do CT 116 no próximo deploy do admin (exige o
  código deste PR).
- O alvo `192.168.0.120` já teve conflito de ARP com outro aparelho (MAC `bc:24:11:06:70:6e`, bead
  `leia-lab-1g1.10`). O ARP fixo está no pve, mas não no CT 103, que também roda Newt: identifique o
  aparelho ou fixe o ARP no CT 103 também.
