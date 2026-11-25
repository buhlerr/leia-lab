# Operação da Leia (M6)

Como o que está em produção no homelab é protegido, restaurado e vigiado. Acesso ao CT 116: pelo host
Proxmox (`pve`, 192.168.0.9) com `pct exec 116`. **Não use SSH direto em 192.168.0.120**: outro
aparelho na rede já respondeu por esse IP (conflito de ARP, ver bead `leia-lab-1g1.10`).

## Instância reserva na VPS `acfs` (desde 2026-11-24)

Em 2026-11-24 o homelab parou de responder (`ssh pve` em timeout). Não tinha caído: o CT 101
(`docker`) bateu no limite de 2 GB de memória e passou a reler o próprio código do disco sem parar
(load 145, SSD 97% ocupado), o que deixou todos os CTs lentos, a Leia inclusive. Resolvido no mesmo
dia: limite do CT 101 subiu para 3 GB e o Coolify (4 containers) foi parado, com `restart=no`, sem
apagar nada.

Antes do diagnóstico, a Leia subiu **do zero** na VPS `acfs` como reserva, sem os dados do CT 116: não
havia cópia dele fora do homelab (o bucket R2 `homelab-pbs` só tem os CT 100, 109, 111, 113 e a VM
200; bead `leia-lab-usd`). A produção continua no CT 116; nada público aponta para a VPS. Parada
em 2026-11-24 com `docker compose stop` (volume e arquivos mantidos); `sudo docker compose start` religa.

| Peça | Estado |
|---|---|
| Pasta | `/data/leia-prod` (fora do repo, `chmod 711`): `docker-compose.yml` (projeto `leia-prod`), `app-<sha>/` (o `git archive` do build) e os `.env` (`chmod 600`: `pg.env`, `roles.env`, `api.env`, `django.env`) |
| Imagem | `leia-api:3f85ca0` (`origin/master`), a mesma para API e admin |
| Postgres | container `leia-prod-postgres`, `127.0.0.1:5434`, volume `leia-prod_leia_prod_pgdata`. **Não** é o de testes da 5433 |
| API | container `leia-api`, `127.0.0.1:18080` (a 8080 da VPS é de outro serviço) |
| Admin | container `leia-admin`, `127.0.0.1:18000`; superusuário `admin`, senha em `django.env` |
| Dados | `init --real` + `apply-matrix --versao v3`: sem as edições do admin nem o histórico do CT 116 |
| Modelos | offline (chaves em branco no `api.env`); embeddings da base são `offline-hash-v1` e precisam de reindexação quando a chave real entrar |
| Acesso público | nenhum: o túnel `homelab` aponta para o CT 116 |
| Backup | **nenhum ainda** (bead `leia-lab-uwc`) |

Os comandos rodam com `sudo docker` (o usuário `ubuntu` não está no grupo `docker`):

```bash
cd /data/leia-prod && sudo docker compose ps
curl -sf http://127.0.0.1:18080/healthz
ssh -L 18000:127.0.0.1:18000 acfs   # admin em http://localhost:18000/admin/ a partir do seu PC
```

O que entrar aqui (análises, edições do admin) não volta sozinho ao CT 116 (bead `leia-lab-uwc`).

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

O Newt e o Pangolin continuam instalados para os outros serviços; a chave da API do Pangolin (1Password,
item `Pangolin API Key - leialab` do cofre `DEV`) só vale para eles.

## Admin: https://admin.rauvbr.com

O Django Admin (`src/management/`) por trás do Cloudflare Access e do login do Django (grupos `editor` e
`leitor`). Superfície: edição da **matriz de risco** (histórico em `domain_history`), a página **Nova
análise** (o arquivo vai pelo servidor à API, ver "Rastreio da API") e, para cada análise, o **relatório
e a trilha** gravados na auditoria do Postgres.

## API para a camada FE: https://leia-api.rauvbr.com

| Peça | Estado (2026-11-21) |
|---|---|
| Endereço | **https://leia-api.rauvbr.com** (Cloudflare Tunnel `homelab`), SSL, **sem Access**: a barreira é o bearer `LEIA_API_TOKEN` (o FE chama do servidor dele) |
| Caminho | Cloudflare → túnel `homelab` (cloudflared no CT 103) → `192.168.0.120:8080` (CT 116) |
| Serviço | `api` no `/root/leia/docker-compose.yml` (container `leia-api`, imagem `leia-api:<sha>`, build de `/root/leia/api`, separado do `management/` do admin), `entrypoint: python -m src.api`, healthcheck em `/healthz` |
| Segredos | `/root/leia/api.env` (chmod 600): `DATABASE_URL` do login `api_login` (membro de `leia_api`, o papel mínimo da API) e `LEIA_API_TOKEN` (64 hex). Gerados no próprio CT, nunca impressos |
| Porta 8080 na LAN | **fechada**: mesma cadeia `LEIA-ADMIN` da 8000 (`deploy/firewall/`) |
| Modelos | OpenRouter e TypeSafe em modo offline até as chaves entrarem (`leia-lab-8tr.9`); quando entrarem, vão no `api.env` |

Passar o token ao FE: `ssh root@192.168.0.9 pct exec 116 -- grep LEIA_API_TOKEN /root/leia/api.env`. Para
trocar o token, edite o `api.env` e rode `docker compose up -d --no-deps api`.

Superfície: contrato OpenAPI em `/docs`; `GET /v1/analyses/{id}` devolve o relatório e a trilha.
A API não tem rota que liste análises.

Atualizar a API para um commit novo (o admin não é tocado):

```bash
git archive --format=tar.gz -o leia-api-<sha>.tar.gz <sha> pyproject.toml uv.lock src deploy .dockerignore
# no CT 116, em /root/leia: mv api api.bak-<data>; mkdir api; tar -xzf leia-api-<sha>.tar.gz -C api
# troque a tag em image: leia-api:<sha> no compose, então:
docker compose build api && docker compose up -d --no-deps api
```

Commit que muda o `src/db/schema.sql` ou o contrato entre admin e API (ex.: o `Idempotency-Key`
obrigatório do VIT-8) não segue o roteiro acima sozinho. Nessa ordem:

1. Rode `python -m src.cli init` com o `DATABASE_URL` do **dono** das tabelas (`leia`), do código do
   commit novo. O `api_login` e o `django_login` não são donos e não alteram tabela; sem isso a API
   nova falha no INSERT (coluna `idempotency_key` ausente). O init é idempotente e pode rodar com a
   API antiga no ar.
2. Atualize a API **e** o admin para o mesmo commit e suba os dois juntos. O admin antigo não manda o
   header, e a API nova responde 422 a toda "Nova análise" dele.

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
- O 1Password **não** guarda `DATABASE_URL` nem `LEIA_API_TOKEN`: os dois existem só nos `.env` de
  produção do CT 116 (`/root/leia/*.env`), que continuam como estão e não leem do 1Password.
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
   Em seguida tira do fim da descrição de cada bead as seções que o `bd` anexa ao enviar
   (`## Acceptance Criteria`, `## Design`, `## Notes`): a puxada as devolve à descrição, e sem essa
   limpeza cada ida e volta somava uma cópia. Só sai a seção cujo texto é igual ao campo do bead,
   ignorando a formatação que o Linear muda; uma seção editada no Linear fica. Critério de aceite,
   design e notas se editam no Beads.
2. Envia só os beads novos ou alterados (hash de título, descrição, status, prioridade, rótulos e pai):
   os abertos e os fechados que já estão no Linear (para irem a Done lá).
3. Põe no projeto **`leia-lab`** do Linear toda issue deste repo que esteja sem projeto, e tira o
   responsável das issues que acabou de criar: o Linear as atribui ao dono da chave de API, e a puxada
   levaria isso ao Beads, onde um responsável trava `bd ready --unassigned` e o `bd close` dos agentes.
   Atribuir-se a mão no Linear continua valendo e chega ao Beads.

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

## Postgres de produção

| Peça | Onde |
|---|---|
| Banco `leia_lab` (Leia **e** Directus, que dividem o banco) | CT 116, container `leia-lab-postgres`, `192.168.0.120:5432` |
| Tabelas | da Leia: `analyses`, `analysis_trail`, a matriz (`risk_matrix`) e o histórico `domain_history`; as demais do domínio estão em `src/db/schema.sql` |
| Como chegar | pelo `pve` (`192.168.0.9` na LAN, `100.101.28.59` no Tailscale): `ssh pve "pct exec 116 -- docker exec leia-lab-postgres psql -U leia -d leia_lab"` |
| Leitura segura | `default_transaction_read_only=on` antes de ler |

### Papéis de banco (VIT-22)

Criados e concedidos pelo `src/db/schema.sql` (idempotente, versionado); logins pessoais recebem um
papel por `GRANT`. Testado em `tests/test_db_roles.py`.

| Papel | Pode | Quem o usa |
|---|---|---|
| `leia` (login) | tudo: é o dono das tabelas, roda `init`, aplica versões de dado | operação |
| `leia_app` | escrita na matriz e no corpus, leitura do histórico; em `analyses` sem `DELETE`, em `analysis_trail` sem `UPDATE`/`DELETE` | `django_login` (admin) |
| `leia_api` | leitura da matriz e do corpus; em `analyses` só `INSERT`/`SELECT` e `UPDATE` **das colunas do término** (`status`, `minuta_type`, `report`, `finished_at` — coluna nova nasce bloqueada), em `analysis_trail` só `INSERT`/`SELECT` | `api_login` (API) |
| `leia_readonly` | `SELECT` nas tabelas do domínio, nada mais | consultas |

Deploy no CT 116 (roda **após o merge**, com o ok do dono — D2): nada de novo no dia a dia, o `init`
do commit novo cria os papeis e os grants. Só o `api_login` muda de papel:

```bash
# 1. init com o DATABASE_URL do dono (leia), como em qualquer mudanca de schema.sql
# 2. troca do papel do login da API (uma linha, reversivel):
ssh pve "pct exec 116 -- docker exec leia-lab-postgres psql -U leia -d leia_lab \
  -c 'GRANT leia_api TO api_login; REVOKE leia_app FROM api_login;'"
# 3. restart da API, para recriar as conexoes com o papel novo:
ssh pve "pct exec 116 -- docker compose -f /root/leia/docker-compose.yml restart api"
```

Checagem pós-troca (esperado: `edita_matriz = f`, `cria_analise = t`, e o `curl` sem erro):

```bash
ssh pve "pct exec 116 -- docker exec leia-lab-postgres psql -U leia -d leia_lab \
  -c \"SELECT has_table_privilege('api_login', 'risk_matrix', 'UPDATE') AS edita_matriz, \
has_table_privilege('api_login', 'analyses', 'INSERT') AS cria_analise;\""
curl -sf https://leia-api.rauvbr.com/healthz
```

Banco migrado de PG ≤ 14 (não criado do zero no ≥ 15): conferir também que `PUBLIC` não tem
`CREATE` no schema `public` (`SELECT nspacl FROM pg_namespace WHERE nspname = 'public'`; em PG
17 criado do zero já não tem). Se ainda tiver: `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` —
sem isso qualquer login cria tabela no espaço da Leia.

O `django_login` continua em `leia_app`, o papel que edita a matriz. Para dar a alguém só leitura:
`GRANT leia_readonly TO <login>`.

## Minutas de teste e textos do gold

`leia-minutas-teste-mascaradas/` (git-ignored, `LEIA_MINUTAS_DIR`): as minutas de teste já mascaradas e
os textos do conjunto gold. Nunca commitados ou enviados; existem por máquina — hoje no checkout Windows
(`C:\Users\Vitor\dev\leia-lab`) e na VPS (`/data/projects/leia-lab`). O gold roda contra elas
(`src/eval/gold.py`, `gold-run`/`gold-compare` no CLI).

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
