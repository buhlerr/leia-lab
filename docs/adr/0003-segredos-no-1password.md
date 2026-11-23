# ADR-0003: Segredos de desenvolvimento no 1Password, no lugar do Shelve

- **Status:** Aceita
- **Data:** 2026-11-23
- **Decisão do responsável pelo produto:** "Migrar os segredos do projeto para o 1Password" (2026-11-23).

## Contexto

Os segredos de desenvolvimento (chaves pagas do OpenRouter e da TypeSafe, LangSmith) viviam no Shelve, time `vitor`, projeto `LEIA`. O responsável já guarda as outras credenciais no 1Password, inclusive a chave do Linear, e quer um cofre só. Na VPS, o Shelve pedia login interativo, o que travava os agentes.

## Decisão

- Os segredos ficam no 1Password, cofre `DEV`, em itens com a tag `leia-lab` e o sufixo `- leialab` no nome.
- O `.env.op` na raiz é versionado e só tem referências `op://`. Todo comando que precisa de segredo roda como `op run --env-file=.env.op -- <cmd>`. Os valores entram só no processo filho e nunca vão para disco.
- No Windows, a CLI `op` usa o app desktop. Na VPS, os agentes usam uma conta de serviço **só de leitura** no cofre `DEV`, com o token em `~/.config/op/leia-lab.token` (mode 600).
- A migração copiou os 8 valores do Shelve para o 1Password por stdin, sem imprimir nenhum. A conferência foi por hash: os valores do 1Password batem com os do Shelve e, para OpenRouter e TypeSafe, com o `api.env` do CT 116.

## Consequências

- Uma conta de serviço do 1Password não tem as permissões alteradas depois de criada. Escrever no cofre exige uma conta temporária, revogada depois do uso.
- A conta de serviço lê o cofre `DEV` inteiro. O responsável decidiu não criar um cofre só do leia-lab: o `DEV` já é o cofre exclusivo dos acessos dos seus projetos de desenvolvimento.
- Os `.env` de produção no CT 116 continuam fora do 1Password. Trazê-los exige um deploy.
- O Shelve saiu do repositório (`shelve.json` e o bloco do `.gitignore`), por autorização do responsável ("remova o shelve", 2026-11-23). As regras `.env` / `.env.*` do bloco foram mantidas.
