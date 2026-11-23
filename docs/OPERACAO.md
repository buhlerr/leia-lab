# Operação da Leia (M6)

Como o que está em produção no homelab é protegido, restaurado e vigiado. Acesso ao CT 116: pelo host
Proxmox (`pve`, 192.168.0.9) com `pct exec 116`. **Não use SSH direto em 192.168.0.120**: outro
aparelho na rede já respondeu por esse IP (conflito de ARP, ver bead `leia-lab-1g1.10`).

## Acesso ao admin: só por HTTPS, pelo Pangolin

| Peça | Estado (2026-11-16) |
|---|---|
| Endereço | **https://admin.rauvbr.com** (recurso Pangolin id 54, org `vitor`), SSL e **SSO do Pangolin** na frente |
| Caminho | Pangolin (VPS Oracle) → site Newt `proxmox` → `192.168.0.120:8000` (CT 116) |
| HTTP | `http://admin.rauvbr.com` redireciona para HTTPS |
| Porta 8000 na LAN | **fechada**: só os conectores Newt (host pve `192.168.0.9` e CT 103 `192.168.0.128`) passam. Firewall `leia-admin-firewall.service` no CT 116 (cadeia `LEIA-ADMIN` em `DOCKER-USER`, reaplicada no boot) |
| Django | `DJANGO_ALLOWED_HOSTS` e `DJANGO_CSRF_TRUSTED_ORIGINS` com `admin.rauvbr.com`; `DJANGO_BEHIND_HTTPS_PROXY=true` (cookies `Secure`) entra no deploy seguinte |

Quem pode entrar é decidido no Pangolin (recurso → Authentication: usuários e papéis), antes do login
do Django. Para incluir uma pessoa: dê acesso ao recurso no Pangolin **e** crie o usuário no Django nos
grupos `editor` ou `leitor`.

API de integração do Pangolin: `https://pangolin.rauvbr.com/v1` (rota `integration-api-rauvbr` no
`dynamic_config.yml` do Traefik na VPS, backup `dynamic_config.yml.bak-integration-rauvbr-20261116`).
A chave fica no 1Password, item `Pangolin API Key - leialab` do cofre `DEV`, ver "Segredos" abaixo.

Se um Newt mudar de máquina, atualize os IPs em `/usr/local/sbin/leia-admin-firewall.sh` no CT 116 e
rode `systemctl restart leia-admin-firewall`.

## API para a camada FE: https://leia-api.rauvbr.com

| Peça | Estado (2026-11-21) |
|---|---|
| Endereço | **https://leia-api.rauvbr.com** (recurso Pangolin id 57, org `vitor`), SSL, **sem SSO**: a barreira é o bearer `LEIA_API_TOKEN` (o FE chama do servidor dele) |
| Caminho | Pangolin → site Newt `proxmox` → `192.168.0.120:8080` (CT 116) |
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

## Segredos (1Password)

Os segredos de desenvolvimento ficam no 1Password, cofre `DEV`, itens com a tag `leia-lab` (ADR-0003).
O `.env.op` na raiz é versionado e só tem referências `op://`. Os valores entram só no processo filho,
sem `.env` em disco:

```bash
op run --env-file=.env.op -- uv run python -m src.cli gold-run --label real-v1 --trace
```

| Variável | Item no cofre `DEV` |
|---|---|
| `OPENROUTER_API_KEY` | `OpenRouter API Key - leialab` (a chave paga, a mesma do `api.env` do CT 116) |
| `TYPESAFE_API_KEY` | `TypeSafe API Key - leialab` |
| `LANGSMITH_API_KEY` | `LangSmith API Key - leialab` (`LANGSMITH_PROJECT=leia-lab` vai em claro no `.env.op`) |
| `LINEAR_API_KEY` | `Linear` |
| Fora do `.env.op` | `Pangolin API Key - leialab`, `Langfuse - leialab` (o projeto não usa; guardados na migração do Shelve) |

- **Windows:** a CLI `op` usa o app desktop do 1Password (Settings → Developer → Integrate with
  1Password CLI). Rode pelo Git Bash, como antes.
- **VPS:** conta de serviço **só de leitura** no cofre `DEV`, token em `~/.config/op/leia-lab.token`
  (mode 600, fora do git). Antes do `op run`: `export OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/leia-lab.token)"`.
- **Não use `op inject` nem `op read` para gravar valores em arquivo** em sessão de agente.
- Os `.env` de produção no CT 116 (`/root/leia/*.env`) continuam como estão; não leem do 1Password.
- `LEIA_HOMELAB_PG_PASSWORD` / `LEIA_HOMELAB_DIRECTUS_PASSWORD` seguem como variáveis de usuário do Windows.

## Sincronização das tarefas com o Linear

Beads e Linear (time `VIT`, workspace `rauvbr`) sincronizam nos dois sentidos: o que muda no Linear
(fechar, reabrir, prioridade, título) chega ao Beads, e o Linear mostra as tarefas abertas. Em conflito,
vence a edição mais recente. A configuração (`linear.team_id`, `linear.state_map.*`,
`linear.outbound_state_map.*`) fica no banco do Beads e viaja com `bd dolt push` / `bd dolt pull`.

```bash
op run --env-file=.env.op -- scripts/linear-sync.sh --dry-run   # ver antes
op run --env-file=.env.op -- scripts/linear-sync.sh             # sincronizar
```

O script (`scripts/linear_sync.py`) só age quando algo mudou:

1. Pergunta ao Linear se alguma issue do time mudou desde a última rodada; só então puxa.
2. Envia só os beads novos ou alterados (hash de título, descrição, status, prioridade, rótulos e pai):
   os abertos e os fechados que já estão no Linear (para irem a Done lá).
3. Põe no projeto **`leia-lab`** do Linear toda issue deste repo que esteja sem projeto.

O estado (hashes e horário da última rodada) fica em `.local/linear-sync-state.json`, fora do git e por
máquina; sem ele, a rodada é completa (cerca de 40 s). Sem mudanças, a rodada leva uns 2 s. Para forçar
uma rodada completa, apague esse arquivo.

**Não rode `bd linear sync` puro:** ele enviaria as 62 tarefas fechadas antes do espelho, que ficam só no
Beads. Não use `linear.project_id`: no `bd` ele restringe a sincronização a um projeto e bloqueia a
criação de issues novas. Um projeto do Linear por repositório (`PROJECT` no `linear_sync.py`); os épicos
do Beads continuam como issues-pai dentro do projeto.

- Estados: `open` → Todo, `in_progress` → In Progress, `closed` → Done. Na volta, Backlog e Todo viram
  `open`, In Progress e In Review viram `in_progress`, Done, Canceled e Duplicate viram `closed`.
- Rótulos de triagem existem no Linear (`needs-triage`, `needs-info`, `ready-for-agent`,
  `ready-for-human`, `wontfix`). Tipos (`task`, `feature`) não viram rótulo; épicos viram issue-pai.
- Comentários, anexos e dependências não sincronizam.
- Issue criada direto no Linear entra no Beads na próxima sincronização.

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
