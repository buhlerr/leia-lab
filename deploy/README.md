# Deploy do admin (Django) no CT 116

O admin edita as regras (tipos, temas, matriz, prompts) e a base normativa, e mostra histórico,
análises e trilha **só para leitura**. Em produção fica atrás do Pangolin, em https://admin.rauvbr.com,
com a porta 8000 fechada para a LAN (firewall em `deploy/firewall/`). Ver `docs/OPERACAO.md`.

## Uma vez, no Postgres (como dono das tabelas, ex. `leia`)

```sql
-- 1. Schema da Leia (idempotente; o mesmo do init_db). Da raiz do repo:
--    uv run python -m src.cli init        (com DATABASE_URL do dono)
-- 2. Login próprio do admin: membro de leia_app, NÃO dono das tabelas de domínio.
CREATE ROLE django_login LOGIN PASSWORD '<senha>' IN ROLE leia_app;   -- se ainda não existir
GRANT CREATE ON SCHEMA public TO django_login;                       -- só para as tabelas django_*/auth_*
```

Com isso, `domain_history.db_user` mostra `django_login` para tudo que vier do admin. **Quem**, entre
as pessoas, fez a mudança fica no log do próprio Django (`django_admin_log`, tela "Ações recentes").

## Subir

```bash
docker build -f deploy/Dockerfile -t leia-admin .
docker run -d --name leia-admin --restart unless-stopped -p 8000:8000 \
  -e DATABASE_URL='postgresql://django_login:<senha>@<host>:5432/leia_lab' \
  -e DJANGO_SECRET_KEY='<50+ caracteres aleatórios>' \
  -e DJANGO_ALLOWED_HOSTS='admin.rauvbr.com' \
  -e DJANGO_CSRF_TRUSTED_ORIGINS='https://admin.rauvbr.com' \
  -e DJANGO_BEHIND_HTTPS_PROXY=true \
  -e DJANGO_SUPERUSER_USERNAME=admin -e DJANGO_SUPERUSER_PASSWORD='<senha>' \
  leia-admin
```

O `migrate` só cria as tabelas do Django e os grupos `editor` (edita regras e base normativa) e
`leitor` (só vê). Ninguém, nem o superusuário, escreve em histórico, análises ou trilha: o admin
nega, e o banco também nega por grant e por gatilho.

## Análise pela tela

A página **Nova análise** (changelist de análises, grupo `editor` ou superusuário) envia a minuta
pelo servidor à API (`POST /v1/analyses`). Quem grava a análise é a API com o token de serviço;
o login do admin não escreve em `analyses`. O upload espera a resposta em até 300 s, por isso o
gunicorn roda com `--timeout 300`.

Variáveis novas no `django.env`:

```bash
-e LEIA_API_URL='http://leia-api:8080' \
-e LEIA_API_TOKEN='<token de servico da API>' \
-e LEIA_MLFLOW_URL='http://leia-mlflow:5000'   # vazio: o detalhe mostra "sem trace"
```

Variável nova no `api.env` da API:

```bash
-e MLFLOW_TRACKING_URI='http://leia-mlflow:5000'   # vazio: a API nao rastreia nada
```

Com isso cada análise da API grava um trace no MLflow marcado com o `leia.analysis_id`, e o
detalhe da análise no admin linka o trace. O trace da API vai só para o MLflow self-hosted, com
conteúdo mascarado, a mesma política do `--trace` do CLI. A LangSmith fica fora da API.

## Testes

```bash
uv run python -m src.management.manage test src.management.domain   # cria e apaga test_<banco>
```
