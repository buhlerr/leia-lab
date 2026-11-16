# Dados versionados

Decisão da M5 (Q5, 2026-11-16): a matriz de riscos real e a base normativa ficam neste repositório como versões imutáveis, conferidas por sha256.

> Apoio à análise jurídica. A matriz e as criticidades **não foram validadas por advogado**. A revisão humana continua obrigatória.

| Pasta | Conteúdo | Origem |
|---|---|---|
| `matriz/v1.jsonl` | 185 riscos, 31 temas, 503 normas | `buhlerr/leia-kb-legislacao@242d540`, `levantamento/matriz-riscos.jsonl` |
| `matriz/v2.jsonl` | 184 riscos, 31 temas, 500 normas | `matriz/v1.jsonl` + `gold/reviews/2026-11-16-locacao-02.json`: `R054` virou vermelho e `R176` saiu |
| `base-normativa/v1/` | 330 artigos (leis, súmulas e teses) | `buhlerr/leia-kb-legislacao@08ab98d`, `saida/` |

## Como funciona

1. `python -m src.cli init --real` aplica o schema e o seed padrão, indexa a base normativa e troca a matriz ativa pela `v1`. O comando é idempotente e retomável. Indexar a base gera embeddings, que são pagos com a `OPENROUTER_API_KEY`. Uma versão só de matriz, como a `v2`, entra sem reindexar a base: `python -m src.cli apply-matrix --versao v2 --base-versao v1`.
2. Cada versão entra no banco **uma vez só** e fica registrada na tabela `data_versions` (nome e sha256), que é append-only. Os riscos que saem da versão nova são desativados, não apagados; os que mudam são atualizados na mesma linha, e o `domain_history` registra a troca.
3. Depois disso, **o banco é a fonte da verdade**: as edições são feitas pelo admin e ficam auditadas. Uma versão publicada nunca muda. Se o arquivo de uma versão for alterado, a aplicação recusa, porque o sha256 não bate com o manifesto ou com o banco. Para congelar novas mudanças, crie a próxima versão (`v3`) com um manifesto novo.

As normas da matriz vêm como `{norma, artigo}` e viram a citação `"<norma>, art. <artigo>"`, que é o título do artigo na base. Uma norma que não dá para mapear gera erro, em vez de ser descartada (bead `leia-lab-vz3`).

`.gitattributes` marca `data/**` como `-text`, para o Git não converter fins de linha e não mudar o sha256.
