# ADR-0001: Decisões de produto antes de escolher o motor e o framework de gestão

- **Status:** Aceita
- **Data:** 2026-11-15
- **Bead:** leia-lab-1g1.1 (épico leia-lab-1g1)
- **Decisão sucessora prevista:** ADR-0002 (motor e framework de gestão)

## Contexto

Existem hoje duas implementações do LEIA, e nenhuma delas cobre sozinha o que o produto precisa.

1. **`master`: grafos LangGraph** (`src/graphs/`: ingestão, consulta e análise de minuta). É a evolução dos fluxos do Langflow. O Jev classifica o tipo da minuta, monta a ficha, tria as cláusulas e confirma os riscos da matriz. O LLM só redige a explicação. A validação é determinística e a criticidade vem da matriz. Há mascaramento de dados pessoais (`src/ingest/masking.py`). Não há interface de gestão nem de uso.
2. **Branch não integrada `buhlerr/resume-previous-work-session` ("acornworm")**: pipeline em pydantic-ai com tipos de minuta e prompts de relatório guardados no banco, interface Streamlit com página de administração, extração de arquivo isolada, defesa contra prompt injection, configuração DeepSeek/OpenRouter com retenção zero e cerca de 107 testes. **Não mascara dados pessoais.**

Antes de escolher o motor (LangGraph, pydantic-ai ou outro) e a ferramenta de gestão, a equipe precisava fechar o que o produto exige, para que a escolha seja feita contra requisitos e não por preferência. As decisões abaixo saíram de uma entrevista de esclarecimento com o responsável pelo produto em 2026-11-15 e estão registradas como foram tomadas.

## Decisões

**Escopo**

- **Q1.** O escopo agora é **locação residencial**. O motor precisa ter o conceito de **tipo de minuta**, porque outros tipos virão em seguida.

**Privacidade**

- **Q2.** Mascarar dados pessoais é suficiente para enviar o texto da minuta a qualquer provedor, inclusive Jev/TypeSafe. **O mascaramento é obrigatório antes de toda chamada externa.** Entendimento atual, **ainda sem fonte citável e a confirmar** (informado pelo responsável do produto na entrevista de 2026-11-15; não foi verificado na política ou nos termos da TypeSafe, e deve ser revisto quando eles forem consultados): a TypeSafe não treina com as entradas, processa nos EUA, não declara prazo de retenção, e a retenção zero só existe sob pedido no plano enterprise.

**Gestão sem desenvolvedor**

- **Q3/Q4.** A interface de gestão deve permitir que quem não é desenvolvedor gerencie: tipos de minuta e seus prompts; matriz de riscos e temas; base normativa (ingestão de leis e jurisprudência); histórico das análises e a trilha de cada uma. O responsável considera ferramentas do ecossistema LangGraph ou similares.

**Avaliação, não escolha**

- **Q5.** A avaliação cobre **a camada de interface/gestão e o framework do motor**. A escolha entre (A) motor LangGraph com casca do acornworm, (B) pydantic-ai do acornworm como produto, ou (C) os dois, fica **suspensa até o fim da avaliação**.
- **Q9/Q11.** A avaliação é uma pesquisa com fontes citadas de até cerca de 5 candidatos, mais protótipos mínimos e descartáveis de 2 finalistas.

**Domínio**

- **Q6.** **Cada tipo de minuta exige a sua própria matriz de riscos.** A criticidade vem da matriz, nunca do LLM (como já descreve o README do repositório externo [`buhlerr/leia-kb-legislacao`](https://github.com/buhlerr/leia-kb-legislacao), que não faz parte deste repositório).

**Critérios de escolha**

- **Q7.** Ferramentas SaaS são aceitáveis.
- **Q8.** O único requisito obrigatório é uma **trilha auditável por análise**: o que cada etapa decidiu e por quê. Critérios de desempate, nesta ordem de apresentação: administração utilizável por não desenvolvedores; avaliação embutida contra um conjunto de referência (gold set); pouca reescrita do código existente.

**Processo**

- **Q10.** **Congelamento de código:** só correções até a decisão do framework (ADR-0002).
- **Q12.** Esta ADR e o glossário agora; o ADR-0002, com o framework, depois da avaliação.

## Consequências

- **Congelamento.** Nenhuma funcionalidade nova é escrita em `master` nem na branch acornworm até o ADR-0002. Correções de defeito continuam permitidas.
- **Épico de avaliação.** O trabalho passa a ser conduzido pelo épico `leia-lab-1g1`, que termina no ADR-0002 com o esboço de migração.
- **Obrigação de mascaramento.** Qualquer caminho que envie texto de minuta a um serviço externo (Jev, LLM, embeddings, SaaS de gestão ou de observabilidade) deve passar antes por `mask_personal_data`. Isso vale também para os candidatos da avaliação: um SaaS que receba texto de minuta só é elegível se receber o texto mascarado. A máscara cobre formatos conhecidos e nomes ou endereços podem escapar (ver o README do repositório externo [`buhlerr/leia-kb-legislacao`](https://github.com/buhlerr/leia-kb-legislacao), seção "Dados e privacidade"); a decisão Q2 aceita esse risco residual. Se o código do acornworm for mantido, ele precisa ganhar o mascaramento, porque hoje não o tem.
- **Matriz por tipo de minuta.** O modelo de dados e a interface precisam tratar a matriz de riscos e os temas como pertencentes a um tipo de minuta. Hoje o código tem uma única matriz de locação residencial (`DEFAULT_RISCOS`, `DEFAULT_TEMAS`, `load_risk_matrix`), e o tipo `locacao_residencial` está fixo na pergunta de classificação. Adicionar um tipo deve ser dado (matriz e prompts), não código.
- **Criticidade fora do LLM.** O LLM redige a explicação, mas não decide a existência nem a cor de um alerta. Qualquer framework escolhido tem de preservar essa fronteira e a validação determinística.
- **Trilha como requisito eliminatório.** Um candidato que não registre, por análise, o que cada etapa decidiu e por quê, está fora, mesmo que vença nos desempates.

## Opções consideradas

As opções A, B e C da decisão Q5 (motor LangGraph com casca do acornworm; pydantic-ai do acornworm como produto; os dois) são justamente o que a avaliação vai comparar. Esta ADR não escolhe entre elas.
