# LEIA

Apoio à análise jurídica de minutas de contrato: o sistema aponta riscos de cláusulas contra uma matriz e uma base normativa, e a revisão humana continua obrigatória. Hoje cobre locação residencial.

## Language

### Documento e tipo

**Minuta**:
Texto de contrato submetido à análise, ainda sujeito a revisão.
_Avoid_: contrato (quando se fala do documento em análise), documento

**Tipo de minuta**:
Categoria do contrato (hoje só `locacao_residencial`). Define qual matriz de riscos se aplica; uma minuta de outro tipo é "não suportada" e não é analisada.
_Avoid_: tipo de documento, `minuta_type`, `tipo` solto

**Cláusula**:
Trecho da minuta tratado como unidade de análise: uma cláusula ou um item numerado, ou um pedaço dela quando é longa demais.
_Avoid_: item, trecho (o *trecho* é a citação literal dentro de uma cláusula, ver **Alerta**)

**Ficha**:
Resumo dos dados-chave da minuta: início da vigência, prazo, valor do aluguel, garantia e índice de reajuste. Serve de contexto para a checagem dos riscos e para a explicação.
_Avoid_: ficha do contrato, metadados

### Matriz de riscos

**Matriz de riscos**:
Lista de riscos de um tipo de minuta, agrupados por tema, cada um com criticidade, parte prejudicada e normas de fundamento. É a única fonte de criticidade.
_Avoid_: levantamento (é o nome da pasta, não do conceito), checklist

**Tema**:
Assunto de uma cláusula (ex.: reajuste e indexação, garantias locatícias). Agrupa os riscos da matriz e decide quais riscos se checam em cada cláusula.
_Avoid_: categoria, subtema (a matriz tem um subtema à parte, hoje sem uso no código)

**Risco**:
Situação descrita na matriz que torna uma cláusula perigosa para a parte prejudicada. Tem identificador, texto, criticidade e normas.
_Avoid_: alerta, achado

**Criticidade**:
Gravidade de um risco, fixada na matriz: vermelho (mais grave) ou amarelo (a matriz real usa também verde, ver Ambiguidades). Nunca é decidida pelo LLM.
_Avoid_: severidade, cor, nível

**Parte prejudicada**:
Quem o risco prejudica (hoje, o locatário).
_Avoid_: parte (solto)

### Resultado da análise

**Alerta**:
Risco da matriz confirmado em uma cláusula concreta, com o trecho literal, o resumo, a explicação e o fundamento legal. É a unidade do relatório.
_Avoid_: risco (que é o item da matriz, ainda não confirmado em uma cláusula)

**Trilha (de análise)**:
Registro, por cláusula, do que cada etapa decidiu e por quê: triagem, riscos checados e confirmados, normas candidatas e usadas, texto bruto da redação, validação e resultado. Existe para auditoria.
_Avoid_: log, diagnóstico (o código chama o objeto de "diagnóstico")

**Relatório**:
Saída da análise: texto com os alertas ordenados por criticidade e um envelope estruturado em JSON.
_Avoid_: laudo, parecer

### Base normativa

**Base normativa**:
Acervo pesquisável de normas e jurisprudência usado como fundamento, guardado por artigo, súmula ou precedente.
_Avoid_: base de conhecimento, KB, legislação (é só uma parte dela)

**Norma**:
Dispositivo da base normativa que fundamenta um risco ou um alerta: artigo de lei, súmula ou precedente, identificado por uma citação (ex.: "Lei 8.245/1991, art. 37").
_Avoid_: dispositivo, lei, fundamento

### Privacidade

**Mascaramento**:
Troca de dados pessoais da minuta (nomes, CPF, CNPJ, RG, endereço, telefone, e-mail, CEP, dados bancários) por marcadores como `[NOME]` e `[CPF]`. É obrigatório antes de toda chamada externa. Cobre formatos conhecidos; nomes e endereços atípicos podem escapar.
_Avoid_: anonimização, redação, sanitização

## Ambiguidades no código

Termos que o código usa de forma inconsistente. A definição acima é a proposta; o código ainda não a segue.

- **"risco"** tem dois sentidos em `src/graphs/analyze_minuta_graph.py`: o item da matriz (campo `risco`, texto) e a nota de triagem de uma cláusula (`cl["risco"]`, número de 0 a 1, vinda da pergunta `_Q_RISCO`). O segundo deveria se chamar *nota de triagem*.
- **"triado"** muda de sentido no meio do fluxo: em `triar` passa a valer "nota de triagem acima do corte" e, após a checagem da matriz, é sobrescrito por "ao menos um risco confirmado". A mesma flag serve a duas perguntas.
- **Criticidade** aparece como `criticidade_sugerida` (matriz), `cor` (`minuta_rules.py`) e `severity` (relatório), com valores em português (`vermelho`) e em inglês (`red`). Há ainda um terceiro nível, **verde**, que existe na matriz real (28 de 185 riscos) e no código, mas não consta da definição de criticidade pedida (vermelho/amarelo). A matriz real tem os dois e o relatório conta verdes; falta decidir se verde é criticidade ou "sem criticidade".
- **Rebaixamento**: um risco vermelho sem norma de fundamento sai amarelo (`rebaixados_sem_norma`). A criticidade final do alerta pode então diferir da criticidade da matriz.
- **"tipo"**: `tipo` (estado do grafo), `minuta_type` (envelope) e a escolha `nao_suportado` na classificação. O conceito é **tipo de minuta**; `nao_suportado` é um valor de resposta, não um tipo.
- **Norma**: o código fala em `dispositivo` (pergunta ao Jev), `citacao` (identificador), `normas` (lista) e `legal_basis`/`fundamento` (relatório). Além disso, a matriz real (`levantamento/matriz-riscos.jsonl`) guarda cada norma como `{"norma", "artigo", ...}`, enquanto `load_risk_matrix` espera `{"id"?, "citacao"}` e descarta quem não tem `citacao`. Pelo arquivo atual, isso deixaria todas as normas de fora e rebaixaria todo vermelho. Registrado como leia-lab-vz3.
- **Temas**: o padrão embutido (`DEFAULT_TEMAS`, 6 temas) não coincide com os 33 temas da matriz real, e um dos nomes (`obrigo_e_encargos`) parece truncado de "obrigações e encargos".
- **"trilha"**: o texto do README e este glossário usam *trilha*; no código é `trilha` (lista interna) dentro de `diagnostics`/`diag` com chave `clausulas`.
- **"alerta"**: `alertas` (campo da resposta do redator, ainda não validado) e `alerts` (envelope, já validado) são coisas diferentes com o mesmo nome. Só o segundo é um alerta no sentido deste glossário.
