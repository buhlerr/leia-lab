# Camada de registro (bead `leia-lab-1g1.4`, branch `prototype/tracing`)

> Protótipo descartável, publicado e **nunca mergeado** (code freeze, ADR-0001). Roda em cima da
> base F (`prototype/foundation`, `d9bb787`). O grafo da F não mudou: `analyze(graph, config=...)`
> já aceitava `config`, e é por aí que a instrumentação entra.

## Como rodar

```bash
uv sync
# as chaves vêm das variáveis de USUÁRIO do Windows (1Password -> env), nunca de arquivo do repo
uv run python -m src.foundation.cli analyze <minuta> --trace langsmith|langfuse|phoenix
uv run python -m src.foundation.cli gold-run --label v1 --trace phoenix
```

| Ferramenta | Como liga | Onde vê |
|---|---|---|
| **LangSmith** | env vars (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`) | smith.langchain.com |
| **Langfuse Cloud** | OTel/OTLP + Basic auth `pk:sk` (`LANGFUSE_HOST=https://us.cloud.langfuse.com`) | us.cloud.langfuse.com |
| **Phoenix** (self-hosted) | OTel/OTLP para `http://192.168.0.120:6006/v1/traces` | http://192.168.0.120:6006 |

Detalhes que custaram tempo e ficam registrados:

- Phoenix v21 expõe **OTLP/HTTP na 6006** (`/v1/traces`), não na 4318; gRPC é 4317. E exige
  `PHOENIX_ENABLE_AUTH=false` para uso interno sem chave.
- O exporter OTLP usa o endpoint **como veio**: o caminho completo `/v1/traces` é obrigatório.
- A conta Langfuse é da região **US**; as mesmas chaves dão 401 em `cloud.langfuse.com`.
- A API pública de leitura do Langfuse (`/api/public/traces`) responde 410/429 neste tenant; a
  contagem confiável é feita no **payload OTLP** (ver testes).

## O que funcionou

1. **Nenhum texto cru sai do processo.** `tests/test_tracing_privacy.py` sobe um servidor local e
   captura os payloads de Langfuse (OTLP) e LangSmith (cliente apontado para ele): a PII conhecida
   da minuta sintética (nome, CPF, e-mail, nome do arquivo) **não aparece**; o texto mascarado
   (`[NOME]`, `[CPF]`) aparece — prova de que o trace foi realmente capturado.
2. **Gabarito compara 2 versões com tracing ligado**: `gold-run v1` → editar `R-04` → `gold-run v2`
   → `gold-compare` mostra `matrix_version 080154455eab → d380b2df0ad9`. As métricas não mudam
   porque o Jev offline é stub (limite da F, não do rastreio).
3. **Depuração**: os spans manuais nos clientes httpx (`call_jev`, `chat_completion`) dão a visão
   por chamada que a instrumentação automática do LangGraph não daria, já que os clientes são
   HTTP cru.

## Limites gratuitos medidos

| Ferramenta | Plano grátis | Medido por análise | Margem |
|---|---|---|---|
| **Phoenix self-hosted** | sem limite (infra própria) | **107 spans** (análise real, 32 alertas) | só disco/RAM do CT (<1 GB) |
| **Langfuse Cloud Hobby** | 50.000 unidades/mês | **~108 unidades** (107 observações + 1 traço) | **~460 análises/mês** |
| **LangSmith Developer** | 5.000 traços/mês | **1 traço** (9 runs, 1 raiz) | **~5.000 análises/mês** |

**A unidade é o que decide.** O Langfuse cobra traço **+ cada observação** + score; a LangSmith
cobra “All traces”, e trace = a árvore inteira (1 raiz). Medido com a mesma minuta real: a
LangSmith envia 9 runs mas conta **1**; o Langfuse conta **~108**. É uma diferença de ~10× na
margem que vem da definição de unidade, não do tamanho do plano.

O número varia com o tamanho da minuta: o grafo faz 1 chamada Jev por cláusula × risco candidato.
A análise sintética de 2 cláusulas gera 17 spans; a real gera ~107. **O orçamento tem de ser feito
com a minuta real**, não com a sintética.

## O que faltou

- O LangSmith foi medido em runs/traços com a minuta real (9 runs, 1 raiz ⇒ 1 traço cobrado), mas
  a confirmação final é no painel de billing da conta (consumo aparece com atraso de minutos).
- Nenhuma ferramenta registra, por si só, *qual versão da matriz* decidiu — isso continua na
  trilha do Postgres (design da F). O rastreio é a vista de depuração, não a fonte da auditoria.
- O Langfuse Cloud Hobby dá 2 usuários; o time maior exige plano pago.

## Arquivos

| Peça | Onde |
|---|---|
| Setup das 3 ferramentas | `src/tracing/__init__.py` |
| Spans manuais nos clientes LLM | `src/clients/jev.py`, `src/clients/llm.py` |
| Flag `--trace` | `src/foundation/cli.py` |
| Prova de privacidade | `tests/test_tracing_privacy.py`, `tests/_capture.py` |
| Contagem de unidades por análise | `tests/test_tracing_units.py` |
