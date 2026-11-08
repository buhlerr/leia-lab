# Schema de configuracao: tipos de minuta e relatorios

## 1. A tarefa em uma frase

Escrever o DDL de `minuta_types` e `minuta_reports` em `src/db/schema_config.sql:15`
de forma que **o prompt seja dado, nao codigo**: trocar um prompt, um modelo ou a
ordem dos relatorios deve ser um `UPDATE`, e o banco deve recusar sozinho uma
configuracao incoerente.

Por que importa: o pipeline de analise vai ler essa tabela a cada execucao
(`WHERE minuta_type_id = $1 ORDER BY execution_order`). Se o banco aceitar lixo
(prompt vazio, `kind` digitado errado, duas etapas com a mesma ordem), o erro so
aparece la na frente, no meio de uma chamada ao LLM. Cada constraint que voce
escrever e um bug que nunca chega no Python.

## 2. Mapa de conceitos (em ordem de dependencia)

1. Chave primaria UUID e `gen_random_uuid()`
2. Foreign key e a acao `ON DELETE`
3. Restringir um dominio de valores: TEXT livre, `CHECK ... IN`, `ENUM`
4. `NOT NULL`, `DEFAULT` e o significado de NULL
5. `CHECK` de conteudo (texto nao vazio, numero positivo)
6. `UNIQUE` simples e composto
7. Constraints `DEFERRABLE`
8. Indices: a FK nao cria indice; indice composto e ordem das colunas
9. `updated_at`: trigger vs aplicacao
10. Idempotencia do DDL

---

## 3. Conceitos

Todos os exemplos sao de uma **loja** (categorias, produtos, etapas de um
checkout). Transfira a ideia; nao copie a forma.

### 3.1 PK UUID e `gen_random_uuid()`

**O que e:** um identificador gerado pelo proprio banco no `INSERT`.

**No projeto:** `src/db/schema.sql:4` e `:12` usam
`id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.

**Detalhe:** desde o PostgreSQL 13, `gen_random_uuid()` e nativa do core. O
`CREATE EXTENSION IF NOT EXISTS "pgcrypto"` em `schema_config.sql:13` e inofensivo,
mas nao e mais obrigatorio no PG 17. Vale saber o motivo de cada linha que voce
mantem.

**Armadilha:** esquecer o `DEFAULT` faz todo `INSERT` precisar mandar o id.

### 3.2 Foreign key e `ON DELETE`

**O que e:** a FK garante que a linha filha aponta para um pai que existe. O
`ON DELETE` diz o que acontece com os filhos quando alguem apaga o pai.

```sql
-- loja: produto pertence a uma categoria
CREATE TABLE produtos (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    categoria_id UUID NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT
);
```

| Acao | Efeito ao apagar o pai |
|---|---|
| `NO ACTION` (padrao) | erro, verificado no fim do statement (pode ser deferido) |
| `RESTRICT` | erro, verificado na hora, nao pode ser deferido |
| `CASCADE` | apaga os filhos junto |
| `SET NULL` / `SET DEFAULT` | desliga os filhos do pai |

**No projeto:** `src/db/schema.sql:13` usa `ON DELETE CASCADE` para chunks: um
chunk sem documento nao tem sentido nenhum, e chunks sao regeraveis a partir do
documento. Pergunte-se se um relatorio configurado (com um prompt que alguem
levou horas para calibrar) tem a mesma natureza "descartavel" de um chunk.

**Armadilha:** repare que `doc_id` em `schema.sql:13` aceita NULL. Uma FK nula
**nao e verificada**: a linha simplesmente fica orfa de nascenca. FK sem
`NOT NULL` quase sempre e um bug.

### 3.3 Dominio de valores: TEXT livre, CHECK, ENUM

**O problema:** a coluna so deve aceitar um conjunto pequeno de valores.

```sql
-- opcao A: texto livre (validacao so na aplicacao)
metodo_pagamento TEXT NOT NULL

-- opcao B: CHECK com lista
metodo_pagamento TEXT NOT NULL
    CHECK (metodo_pagamento IN ('pix', 'cartao', 'boleto'))

-- opcao C: tipo enumerado
CREATE TYPE metodo_pagamento_t AS ENUM ('pix', 'cartao', 'boleto');
metodo_pagamento metodo_pagamento_t NOT NULL
```

- **TEXT livre:** zero atrito para evoluir; `'Pix'`, `'pix '` e `'pxi'` entram todos.
- **CHECK:** o banco recusa erro de digitacao; adicionar valor = `DROP CONSTRAINT`
  + `ADD CONSTRAINT` (o ADD revalida a tabela inteira). Fica so nesta tabela.
- **ENUM:** tipo reutilizavel e compacto (4 bytes); adicionar valor e facil
  (`ALTER TYPE ... ADD VALUE IF NOT EXISTS`), mas **remover ou renomear e
  doloroso**, e `CREATE TYPE` **nao tem `IF NOT EXISTS`** (precisa de um bloco
  `DO $$ ... EXCEPTION WHEN duplicate_object ...`). Drivers como asyncpg devolvem
  o ENUM como `str`, entao o Python nao percebe diferenca.
- (Opcao D, citada para completar: uma tabela de lookup com FK. Mais pesado,
  util quando o valor carrega atributos proprios.)

**Armadilha:** `CHECK (x IN (...))` em coluna **nula** passa, porque
`NULL IN (...)` da NULL, e CHECK so rejeita FALSE. CHECK sem `NOT NULL` deixa a
porta aberta.

**Sobre quais valores de `kind`:** pense em `kind` como "**como o pipeline
processa a saida deste relatorio**", nao "sobre o que ele fala". Algumas
categorias candidatas para voce avaliar:

- saida **estruturada** (o LLM devolve JSON que vai ser validado por schema);
- **parecer** livre em texto (vai para leitura humana, sem parse);
- **checklist** (itens com status, ex.: presente/ausente/divergente);
- **resumo** (texto curto, talvez alimentando outro relatorio).

A pergunta que decide se dois valores sao realmente diferentes: *o codigo que
consome a saida e diferente?* Se nao for, provavelmente e o mesmo `kind` com
prompts diferentes. Se a lista e algo que voce espera mudar todo mes, isso pesa
na escolha entre A, B e C.

### 3.4 NOT NULL, DEFAULT e o significado de NULL

NULL nao e "vazio", e "nao se sabe / nao se aplica". Quando voce permite NULL,
voce precisa **dar um significado** a ele e documentar.

```sql
-- loja: frete NULL significa "usa a tabela de frete padrao da loja"
frete_fixo NUMERIC(10,2)          -- NULL = regra padrao
-- versus
frete_fixo NUMERIC(10,2) NOT NULL -- sempre explicito
```

**Conexao com o projeto:** `src/config.py:10` define `CHAT_MODEL`. Um `model`
nulo pode significar "usa `Settings.CHAT_MODEL`" (o Python faz o fallback). Agora
releia o comentario de `src/db/schema.sql:18-19`: a procedencia do embedding foi
gravada justamente porque trocar o default **em silencio** mistura resultados.
O mesmo dilema vale aqui: com NULL, mudar uma variavel de ambiente muda o modelo
de todos os relatorios sem nenhum `UPDATE` no banco. Isso e vantagem ou risco?

**Armadilha:** `DEFAULT` so age quando a coluna e **omitida** no INSERT. Um
`INSERT ... VALUES (..., NULL)` explicito grava NULL, mesmo com DEFAULT.

### 3.5 CHECK de conteudo

`NOT NULL` aceita `''` e `'   '`. Para texto que precisa ter conteudo:

```sql
-- loja: descricao do produto nao pode ser vazia nem so espacos
descricao TEXT NOT NULL CHECK (length(btrim(descricao)) > 0)

-- loja: posicao na vitrine comeca em 1
posicao INT NOT NULL CHECK (posicao > 0)
```

**Armadilha:** de nome as constraints (`CONSTRAINT produtos_descricao_nao_vazia
CHECK (...)`). O nome aparece na mensagem de erro e e o que voce usa num
`DROP CONSTRAINT` futuro. Sem nome, o PG inventa um (`produtos_descricao_check`).

### 3.6 UNIQUE simples e composto

```sql
-- loja: nome de categoria unico na loja toda
nome TEXT NOT NULL UNIQUE

-- loja: dentro de uma categoria, dois produtos nao ocupam a mesma posicao
UNIQUE (categoria_id, posicao)
```

Um UNIQUE composto diz "a **combinacao** e unica": a posicao 1 pode existir em
varias categorias, mas so uma vez em cada.

Perguntas para cada candidato a UNIQUE:
- Se existirem duas linhas iguais, o sistema quebra ou so fica feio?
- O codigo vai buscar por essa coluna (ex.: "pega o relatorio chamado X")? Se
  sim, sem UNIQUE a busca pode devolver duas linhas.
- Unicidade e sensivel a caixa? `'Locacao'` e `'locacao'` sao iguais para voce?
  (Se sim, a ferramenta e um indice unico em `lower(nome)`, nao um UNIQUE simples.)

**Armadilha:** NULL nao colide com NULL em UNIQUE (dois NULL sao "distintos").
No PG 15+ existe `UNIQUE NULLS NOT DISTINCT` se voce precisar do contrario.

### 3.7 DEFERRABLE

**O problema:** trocar a ordem de duas etapas.

```sql
-- loja: etapas do checkout, (fluxo_id, ordem) unico
-- quero trocar a etapa 1 com a etapa 2
UPDATE etapas_checkout SET ordem = 3 - ordem
 WHERE fluxo_id = $1 AND ordem IN (1, 2);
```

Com um UNIQUE normal (nao deferrable), o PG verifica **linha a linha**: ao mudar
a primeira linha para 2, a outra ainda esta em 2, e da erro de duplicata, mesmo
que o estado final seja valido.

Tres modos:

| Declaracao | Quando verifica |
|---|---|
| (padrao) `NOT DEFERRABLE` | a cada linha |
| `DEFERRABLE INITIALLY IMMEDIATE` | no fim de cada **statement**; pode ser adiado com `SET CONSTRAINTS nome DEFERRED` dentro da transacao |
| `DEFERRABLE INITIALLY DEFERRED` | sempre no `COMMIT` |

```sql
BEGIN;
SET CONSTRAINTS etapas_checkout_fluxo_ordem_key DEFERRED;
UPDATE ... ;   -- estado intermediario pode ter duplicata
UPDATE ... ;
COMMIT;        -- aqui o banco confere
```

**Custos:**
- `INSERT ... ON CONFLICT` **nao aceita** uma constraint deferrable como arbitro.
  Se voce pretende fazer upsert por essa chave (ex.: num seed), isso pesa.
- So constraints (`UNIQUE`, `PRIMARY KEY`, `FOREIGN KEY`, `EXCLUDE`) podem ser
  deferrable. `CHECK`, `NOT NULL` e `CREATE UNIQUE INDEX` nao.
- Alternativa sem deferrable: renumerar em dois passos (ex.: jogar para negativos
  e depois para os valores finais), ou usar ordens com folga (10, 20, 30).

### 3.8 Indices: a FK nao cria indice

O PG cria indice automaticamente para `PRIMARY KEY` e `UNIQUE`, **nao** para o
lado filho de uma FK.

**No projeto:** por isso `src/db/schema.sql:32` cria `idx_kb_chunks_doc_id` na mao.

Um indice btree em `(a, b)` serve:
- `WHERE a = $1` (usa o prefixo);
- `WHERE a = $1 ORDER BY b` (ja devolve ordenado, sem Sort);
- **nao** serve bem `WHERE b = $1` sozinho.

```sql
-- loja: "produtos da categoria X na ordem da vitrine"
SELECT * FROM produtos WHERE categoria_id = $1 ORDER BY posicao;
-- um btree com categoria_id na frente e posicao depois atende tudo
```

**Pergunta-chave:** se voce ja tiver um UNIQUE cujas colunas, na ordem certa,
sao exatamente as da consulta, quantos indices voce precisa criar a mais? Um
indice duplicado custa escrita e espaco sem ganho.

### 3.9 `updated_at`

`DEFAULT now()` so roda no INSERT. Num UPDATE a coluna fica com o valor velho.

```sql
-- loja: carimbo automatico via trigger
CREATE OR REPLACE FUNCTION carimba_atualizado_em() RETURNS trigger AS $$
BEGIN
    NEW.atualizado_em := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER produtos_carimbo   -- OR REPLACE existe desde o PG 14
BEFORE UPDATE ON produtos
FOR EACH ROW EXECUTE FUNCTION carimba_atualizado_em();
```

| Trigger | Aplicacao |
|---|---|
| vale para qualquer cliente (psql, Beekeeper, Python) | so vale quando o UPDATE passa pelo seu codigo |
| logica "escondida" no banco | explicito no repositorio |
| uma funcao reaproveitavel por N tabelas | cada UPDATE precisa lembrar |

Contexto: o caso de uso declarado e "mudar um prompt e um UPDATE", e esse UPDATE
provavelmente vai ser feito no Beekeeper, na mao.

**Armadilha:** `now()` e o horario do **inicio da transacao**, nao do statement.
Duas alteracoes na mesma transacao recebem o mesmo carimbo.

### 3.10 Idempotencia

**No projeto:** `src/db/schema.sql` inteiro roda de novo sem erro
(`IF NOT EXISTS` em tabela, indice e coluna, linhas 3, 11, 26-33).

O que `CREATE TABLE IF NOT EXISTS` **nao** faz: se a tabela ja existe com outro
formato, ele nao muda nada, nem avisa alem de um NOTICE. Constraints novas numa
tabela existente exigem `ALTER TABLE ... ADD CONSTRAINT`, que nao tem
`IF NOT EXISTS` (padrao comum: `DROP CONSTRAINT IF EXISTS` seguido de `ADD`).
Ja viu no `schema.sql:25-27` esse problema resolvido para colunas.

**Observacao:** hoje `src/db/connection.py:21` e `:54-61` so leem `schema.sql`.
Seu arquivo novo ainda nao e aplicado pelo `init_db`; para testar, voce vai
aplicar na mao (secao 5).

---

## 4. Decisoes que voce vai tomar

Sem resposta certa universal. Escreva um comentario curto no SQL justificando
cada escolha: e isso que vai separar "copiei um padrao" de "desenhei um schema".

1. **ON DELETE da FK.** `CASCADE`: apagar um tipo limpa tudo, sem orfaos, mas um
   `DELETE` errado leva junto prompts calibrados. `RESTRICT`/`NO ACTION`: obriga
   apagar os relatorios antes (ou desativar em vez de apagar), protege contra
   acidente, da mais trabalho em limpeza de teste. Note que o `conftest.py:45`
   derruba o schema inteiro, entao os testes nao sao afetados pela escolha.
2. **Como restringir `kind`** (3.3) e **quais valores** existem. Quanto voce
   espera que essa lista mude? Quem sofre se um valor invalido entrar?
3. **Unicidade.** `UNIQUE(minuta_type_id, execution_order)`: duas etapas na mesma
   posicao seriam um empate - qual roda primeiro? `UNIQUE(minuta_type_id, name)`:
   dois relatorios homonimos no mesmo tipo confundem quem le o resultado?
   `name` unico em `minuta_types`: o codigo vai procurar tipo por nome?
4. **`model` nulo ou obrigatorio** (3.4). Conveniencia de um default central vs
   reprodutibilidade: "que modelo gerou este relatorio de marco?".
5. **CHECK de prompt nao vazio** e outros CHECKs (ordem > 0? nomes nao vazios?).
6. **DEFERRABLE** no UNIQUE de ordem (3.7): reordenar facil vs perder `ON CONFLICT`.
7. **Indice** para `WHERE minuta_type_id = $1 ORDER BY execution_order` (3.8):
   ja vem de graca de alguma constraint sua, ou precisa criar?
8. **`created_at`/`updated_at`**: existem? Atualizados por trigger ou pela
   aplicacao (3.9)?
9. **Idempotencia** (3.10): o arquivo roda duas vezes seguidas sem erro? E se
   tiver ENUM?
10. **Tipos de texto:** `TEXT` vs `VARCHAR(n)`. No PG sao o mesmo armazenamento;
    `VARCHAR(n)` so adiciona um limite. Um limite em `prompt` ajuda ou atrapalha?

## 5. Como testar o que voce escreveu

Use o banco de teste (`leia_lab_test`, `src/config.py:7`) ou envolva tudo em
`BEGIN; ... ROLLBACK;` para nao sujar o banco de desenvolvimento.

Aplicar o arquivo (do Windows, mandando o arquivo pelo stdin do ssh):

```bash
ssh homelab-docker "docker exec -i leia-lab-postgres psql -U leia -d leia_lab_test -v ON_ERROR_STOP=1" < src/db/schema_config.sql
```

Rode **duas vezes**. A segunda tem que passar sem erro (idempotencia).

Inspecionar (dentro do `psql`):

```sql
\d minuta_types
\d minuta_reports
-- todas as constraints, com definicao e se sao deferrable
SELECT conname, contype, condeferrable, condeferred, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'minuta_reports'::regclass;
-- indices existentes (procure duplicados)
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'minuta_reports';
```

Monte voce mesmo uma bateria de INSERTs/UPDATEs. Para cada regra que voce
decidiu, escreva **um comando que deve falhar** e confira a mensagem:

- relatorio apontando para um `minuta_type_id` inexistente;
- `kind` com um valor fora da sua lista (e com `NULL`);
- prompt `''` e prompt `'   '`;
- duas linhas com a mesma ordem no mesmo tipo (e a mesma ordem em tipos
  diferentes, que deve **passar**);
- `DELETE` de um tipo que tem relatorios: o que acontece bate com o que voce
  escolheu?
- troca de ordem entre dois relatorios num unico `UPDATE` (3.7), com e sem
  `SET CONSTRAINTS ... DEFERRED`;
- um `UPDATE` no prompt seguido de `SELECT` do `updated_at` (se existir).

Verificar o indice (tabela pequena faz o planner preferir Seq Scan, entao force):

```sql
SET enable_seqscan = off;
EXPLAIN SELECT * FROM minuta_reports
 WHERE minuta_type_id = gen_random_uuid() ORDER BY execution_order;
RESET enable_seqscan;
```

Procure `Index Scan using ...` **sem** um no `Sort` acima.

Depois rode a suite: `pytest tests/` (o contrato em `schema_config.sql:7-11`
cita os testes e `config_repo.py` que ainda vao consumir isso).

## 6. Perguntas de checagem

1. Uma coluna `TEXT CHECK (x IN ('a','b'))` sem `NOT NULL` aceita qual valor
   "fora da lista"? Por que?
2. Por que um UNIQUE comum falha em `UPDATE t SET ordem = 3 - ordem WHERE ordem IN (1,2)`
   e um `DEFERRABLE INITIALLY IMMEDIATE` nao?
3. Voce criou `UNIQUE(fk, ordem)`. Precisa de um `CREATE INDEX` separado em `fk`?
   E em `ordem`?
4. Se `model` for nulo e alguem trocar `CHAT_MODEL` no `.env`, o que muda no
   banco? O que muda nos resultados?
5. Por que o `kb_chunks` pode usar `ON DELETE CASCADE` sem culpa e a decisao
   para relatorios merece mais reflexao?

<details>
<summary>Respostas (tente antes)</summary>

1. `NULL`. `NULL IN ('a','b')` resulta em NULL, e CHECK so rejeita quando a
   expressao e FALSE. Precisa de `NOT NULL` junto.
2. O UNIQUE nao deferrable e verificado a cada linha alterada; no meio do
   statement existem duas linhas com o mesmo valor. O `DEFERRABLE INITIALLY
   IMMEDIATE` verifica so no fim do statement, quando o estado ja e consistente.
   Para varios statements, `SET CONSTRAINTS ... DEFERRED` adia ate o COMMIT.
3. Em `fk`: nao, o btree de `(fk, ordem)` atende buscas pelo prefixo `fk` e ja
   entrega ordenado por `ordem`. Em `ordem` sozinha: so se alguma consulta
   filtrar por `ordem` sem `fk`, o que e improvavel aqui.
4. No banco, nada: nenhuma linha muda. Nos resultados, tudo: a proxima execucao
   de todos os relatorios com `model` nulo usa outro modelo. E exatamente a
   "troca silenciosa" que `schema.sql:18-19` quis evitar para embeddings; se
   isso e aceitavel depende de voce registrar o modelo usado em outro lugar
   (por exemplo, no resultado da execucao).
5. Chunks sao derivados: dao para regenerar a partir do documento. Um relatorio
   configurado e fonte de verdade (o prompt calibrado nao existe em outro lugar),
   entao um cascade acidental perde trabalho humano irrecuperavel.

</details>

## 7. Para ir alem

- Constraints (CHECK, UNIQUE, FK, ON DELETE, NULLS NOT DISTINCT):
  https://www.postgresql.org/docs/17/ddl-constraints.html
- `SET CONSTRAINTS` e constraints deferrable:
  https://www.postgresql.org/docs/17/sql-set-constraints.html
- Indices multicoluna e indices com ORDER BY:
  https://www.postgresql.org/docs/17/indexes-multicolumn.html e
  https://www.postgresql.org/docs/17/indexes-ordering.html
