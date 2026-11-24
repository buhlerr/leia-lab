# Modo offline: como o leia-lab roda sem IA

O leia-lab analisa um contrato inteiro sem chamar nenhuma IA quando as chaves `OPENROUTER_API_KEY` e `TYPESAFE_API_KEY` estão vazias. Nesse modo, cada peça que usaria uma IA devolve uma resposta pronta, escrita no próprio código. A análise vai do começo ao fim e grava o relatório e a trilha, mas nenhum modelo opina sobre o contrato.

Este documento explica a ideia em linguagem simples, mostra o que cada peça responde, traz um exemplo real e diz como rodar nos dois modos.

## A ideia em linguagem simples

### Uma linha de montagem com alguns especialistas

O leia-lab funciona como uma linha de montagem. O contrato passa por etapas, e só algumas delas precisam de um especialista que "pensa".

| Etapa | O que faz | Quem faz | Usa IA? |
|---|---|---|---|
| 1. Ler e mascarar | Lê o arquivo e troca nomes, CPFs e endereços por marcadores como `[NOME]` | Regras no código (`src/ingest/masking.py`) | Não |
| 2. Classificar | Diz se o documento é uma locação residencial | Jev (TypeSafe) | Sim |
| 3. Ficha | Acha data de início, prazo, aluguel, garantia e índice | O código acha os candidatos. O Jev escolhe entre eles | Sim, para escolher |
| 4. Triar | Separa as cláusulas, dá o tema de cada uma e confirma os riscos da matriz | O código separa. O Jev dá notas | Sim |
| 5. Buscar | Acha as leis que se aplicam a cada cláusula arriscada | Busca no banco, com embeddings. O Jev dá nota a cada lei | Sim |
| 6. Redigir | Escreve em português a explicação de cada risco | O redator (`deepseek/deepseek-v4.1-flash`, via OpenRouter) | Sim |
| 7. Validar e gravar | Confere o texto do redator, aplica a gravidade da matriz e grava tudo | Regras no código | Não |

A gravidade de um risco nunca vem da IA. Ela vem da matriz de riscos, que fica no banco e é editada no Admin.

### Dublês no lugar dos especialistas

No modo offline, cada especialista é trocado por um dublê. O dublê não lê o contrato com atenção nem pensa. Ele sempre devolve uma resposta no formato certo, com valores fixos.

Pense num teste de colisão de carro. O boneco no banco do motorista não sente nada e não dirige. Ele está ali para que os engenheiros vejam se o cinto trava e se o airbag abre. Aqui é igual. O dublê ocupa o lugar da IA para que a gente veja se o resto da linha de montagem funciona:

- se os dados pessoais foram escondidos antes de qualquer etapa;
- se as notas de corte separam as cláusulas como deveriam;
- se o limite de gasto corta as cláusulas na ordem certa;
- se o relatório e a trilha são gravados no banco.

O boneco prova que o carro está montado direito. Ele não diz nada sobre como o motorista dirige. Do mesmo jeito, o modo offline não diz nada sobre a qualidade da IA.

### Por que testar assim

- **Não custa nada.** Cada chamada ao OpenRouter e ao TypeSafe é paga.
- **O resultado é sempre igual.** Se um teste falha, o erro está no código, porque o dublê responde a mesma coisa toda vez.
- **Nenhum texto sai da máquina.** O contrato, mesmo mascarado, não vai para nenhum provedor.
- **Roda em qualquer lugar.** Basta o Postgres. Não precisa de chave, de internet nem do 1Password.

## Como o código escolhe o modo

Cada cliente olha a própria chave antes de cada chamada. A chave vazia liga o dublê. Não existe uma chave geral de "modo offline".

| Chave vazia | Peças que viram dublê |
|---|---|
| `OPENROUTER_API_KEY` | O redator e os embeddings |
| `TYPESAFE_API_KEY` | O Jev (classificar, ficha, triar e a nota das leis em buscar) |

As duas chaves são independentes. Com só uma delas preenchida, metade da análise usa IA e a outra metade usa dublê.

As chaves vêm do ambiente ou de um arquivo `.env` na raiz (`src/config.py`). Nenhuma chave fica gravada no repositório. Elas ficam no 1Password, e o `.env.op` guarda só as referências (ADR 0003).

## O que cada dublê responde

Esta tabela descreve o comportamento exato do código.

| Peça | Arquivo | Resposta do dublê |
|---|---|---|
| Redator | `src/clients/llm.py`, função `_offline` | Um JSON com um alerta para cada risco confirmado. O `trecho` são os primeiros 120 caracteres da cláusula, o `resumo` é a descrição do risco na matriz, o `detalhe` é sempre `Análise offline determinística.` e `discorda` é sempre `false`. Custo e tokens são zero |
| Chat sem alertas | `src/clients/llm.py` | A frase fixa `Resposta offline baseada nos trechos fornecidos.` (usada pela consulta, `query_graph`) |
| Embeddings | `src/rag/embeddings.py`, função `_deterministic_embedding` | Um vetor de 1536 números tirado de um hash SHA-256 do texto, gravado com o modelo `offline-hash-v1`. Textos iguais dão vetores iguais. Textos parecidos não dão vetores parecidos |
| Jev, notas (`noul`) | `src/clients/jev.py`, função `_offline_answer` | Sempre `0.75` |
| Jev, tipo do documento | `src/clients/jev.py` | `locacao_residencial` com confiança `0.95` quando o texto tem "locacao", "locação" ou "aluguel" |
| Jev, outras escolhas | `src/clients/jev.py` | A opção `nao_suportado` quando ela existe. Senão, o primeiro candidato da lista (`c0`). Senão, a primeira opção. Sempre com confiança `0.95` |

### O que isso faz com a análise

As notas de corte padrão ficam em `analyze_minuta_graph.py`: triagem `0.2`, confirmação `0.5`, lei `0.3`. Como o dublê do Jev dá sempre `0.75`, o resultado offline é previsível:

- **Toda cláusula passa na triagem**, porque `0.75` é maior que `0.2`.
- **Toda cláusula cai no mesmo tema**, o primeiro da lista de temas da matriz.
- **Todo risco desse tema é confirmado** em todas as cláusulas, porque `0.75` é maior que `0.5`.
- **A ficha pega o primeiro candidato** que o código achou no texto, como a primeira data e o primeiro valor em reais. Na garantia e no índice, que têm opções fixas, ela pega a primeira opção (`caucao` e `igpm`). Quando o código não acha nenhum candidato, ela pega `nao_consta`.
- **A busca de leis não acha o que é parecido**, porque o vetor de hash não carrega sentido. As leis que a matriz liga ao risco entram mesmo assim, porque essa ligação vem do banco.
- **O redator nunca discorda e o trecho é sempre literal**, então a validação nunca encontra problema no texto dele.

Ou seja, um relatório offline não diz nada sobre o contrato. Ele só mostra que as peças se encaixam.

## Um exemplo real

Em 2026-11-24, rodamos `analyze` offline na minuta de teste `locacao-02.txt`, com a matriz padrão do `init` (6 riscos). O resultado foi este:

| Item | Valor |
|---|---|
| Status | `done` |
| Cláusulas encontradas | 21 |
| Cláusulas que passaram na triagem | 21 |
| Tema dado às cláusulas | `benfeitorias_e_conservacao`, em todas |
| Risco confirmado | `R-04` (renúncia à indenização por benfeitorias necessárias), em todas |
| Alertas | 21 amarelos, 0 vermelhos, 0 verdes |
| Ficha | aluguel `R$ 1.500,00`, início `28 de Maio de 2024`, garantia `caucao`, índice `igpm` |
| Custo do redator | US$ 0,00 |

O primeiro alerta aponta para o cabeçalho do contrato, que só tem os nomes das partes:

```text
Contrato de Locação de Imóvel LOCADOR(A): ● Nome: [NOME] ● Nacionalidade: Brasileira ● CPF: [CPF] ...
```

O sistema marcou esse cabeçalho como "renúncia à indenização por benfeitorias". Isso não faz sentido para um advogado, e é o esperado no modo offline. O exemplo também mostra duas coisas que funcionaram de verdade. Os nomes e o CPF chegaram mascarados como `[NOME]` e `[CPF]`. A análise terminou com status `done` e gravou a trilha passo a passo.

A evidência dessa rodada está em `.local/verify-proof/offdoc/`, que é local e não vai para o git.

## O que o modo offline prova e o que não prova

| Prova | Não prova |
|---|---|
| O grafo roda inteiro, de `iniciar` a `validar` | Se a IA classifica o tipo do contrato corretamente |
| O mascaramento acontece antes de qualquer etapa | Se a IA acha os riscos certos nas cláusulas certas |
| As notas de corte e a ordem das cláusulas funcionam | Se a busca acha as leis certas |
| O teto de custo corta as cláusulas e avisa no relatório | Se o redator devolve um JSON válido |
| O relatório e a trilha são gravados e não mudam depois | Se as explicações do redator são boas |
| O nome real do arquivo não aparece em nenhum registro | Quanto uma análise custa de verdade |

Para testar o teto de custo offline, zere o limite com `ANALYSIS_MAX_COST_USD=0`. Offline o custo é sempre zero, então o teto só corta quando o limite também é zero.

O gold set offline também não mede qualidade. O `gold-run` compara os riscos achados com os esperados. Offline, o dublê confirma todos os riscos do primeiro tema em todas as cláusulas, então a nota sai igual em toda rodada. Use o gold offline só para ver se o mecanismo de comparação funciona.

## Como rodar offline

Rode os comandos a partir da raiz do repositório.

### Os testes automáticos

A suíte de testes sempre roda offline, porque `tests/conftest.py` cria as configurações com `OPENROUTER_API_KEY=""`.

```bash
scripts/ci.sh
```

O `ci.sh` precisa do Postgres de teste (`localhost:5433/leia_lab_test`) e de Java 11 ou mais novo.

### Uma análise de ponta a ponta

Use a skill `verify-leia-lab`. Ela cria um banco descartável `leia_lab_verify_<id>` e apaga as duas chaves antes de cada comando. Assim, mesmo que o seu ambiente tenha uma chave, nada é pago.

No VPS (Linux):

```bash
export VERIFY_PG_SERVER=postgresql://leia:leia_lab_2026@localhost:5433
V=".venv/bin/python .claude/skills/verify-leia-lab/scripts/verify.py"
$V launch --run-id r1
$V cli --run-id r1 -- analyze leia-minutas-teste-mascaradas/locacao-02.txt
$V sql --run-id r1 --label alertas "SELECT report->'content'->'counts' FROM analyses"
```

No Windows, em Git Bash, troque o Python por `.venv/Scripts/python.exe`. Os detalhes de cada comando estão em `.claude/skills/verify-leia-lab/SKILL.md`.

Não rode `python -m src.cli` direto para testar. Sem a skill, o comando usa o `DATABASE_URL` e as chaves que estiverem no seu ambiente.

### Como saber se uma rodada foi offline

- Offline, os embeddings imprimem um aviso: `OPENROUTER_API_KEY not set: using deterministic hash embeddings labelled 'offline-hash-v1'`.
- O relatório tem `custo_usd_redacao` igual a `0.0` e `jev_tokens` igual a `0` em `stats`.
- Os alertas têm `detail` igual a `Análise offline determinística.`.
- Num traço (`--trace`), cada chamada leva a marca `offline=true`.

## Como rodar com IA de verdade

Antes de rodar, combine com o responsável pelo projeto. Este modo gasta crédito do OpenRouter e do TypeSafe, e manda texto mascarado para os provedores.

O `op run` busca as chaves no 1Password e as passa só para o comando. Nenhum valor é gravado em disco. No VPS, carregue antes a conta de serviço:

```bash
export OP_SERVICE_ACCOUNT_TOKEN="$(cat ~/.config/op/leia-lab.token)"
```

Depois, rode a análise contra um banco de verificação, nunca contra a produção:

```bash
op run --env-file=.env.op -- env \
	DATABASE_URL=postgresql://leia:leia_lab_2026@localhost:5433/leia_lab_verify_r1 \
	.venv/bin/python -m src.cli analyze leia-minutas-teste-mascaradas/locacao-02.txt
```

Para comparar modelos, rode o gold set duas vezes, trocando o `CHAT_MODEL`, e compare as rodadas:

```bash
op run --env-file=.env.op -- env DATABASE_URL=... CHAT_MODEL=deepseek/deepseek-v4.1-flash \
	.venv/bin/python -m src.cli gold-run --label deepseek
op run --env-file=.env.op -- env DATABASE_URL=... CHAT_MODEL=openai/gpt-4o-mini \
	.venv/bin/python -m src.cli gold-run --label gpt4omini
.venv/bin/python -m src.cli gold-compare deepseek gpt4omini
```

O gold precisa da matriz real, que o `launch --real` aplica. Hoje o `gold-compare` mede só os riscos e a gravidade, que vêm do Jev e da matriz. Ele ainda não compara o texto do redator. A bead `leia-lab-pvw.2` cobre essa comparação.

Até 2026-11-24, nenhuma rodada paga com o `deepseek/deepseek-v4.1-flash` foi feita. O único número de qualidade que existe é o F1 de 0,75 do `gpt-4o-mini` no gold. Em produção (CT 116), as chaves ainda não entraram, e tudo roda offline (`docs/OPERACAO.md`).

## Cuidados

- **Vetores offline e reais não se misturam.** Cada pedaço da base normativa guarda o modelo que gerou o vetor (`embedding_model`). A busca compara só vetores do mesmo modelo. Numa base ingerida offline, uma análise com chave real perde a busca por sentido e fica só com a busca por palavras. O contrário também vale.
- **O banco pode trocar o modelo do redator.** Um prompt `redigir_system` com a coluna `model` preenchida vale no lugar do `CHAT_MODEL`. Confira a coluna antes de comparar modelos.
- **Uma chave só liga metade da análise.** Com só a chave do OpenRouter, o redator é real, mas recebe riscos que o dublê do Jev confirmou.
- **O teto de custo não conta os embeddings.** Eles custam cerca de US$ 0,0001 por análise.

## Onde está no código

| O quê | Onde |
|---|---|
| Configuração e chaves | `src/config.py` |
| Dublê do redator | `src/clients/llm.py`, `_offline` |
| Dublê do Jev | `src/clients/jev.py`, `_offline_answer` |
| Dublê dos embeddings | `src/rag/embeddings.py`, `_deterministic_embedding` |
| Notas de corte e etapas da análise | `src/graphs/analyze_minuta_graph.py` |
| Chaves vazias nos testes | `tests/conftest.py` |
| Verificação de ponta a ponta | `.claude/skills/verify-leia-lab/SKILL.md` |
| Termos do domínio | `GLOSSARY.md` |
