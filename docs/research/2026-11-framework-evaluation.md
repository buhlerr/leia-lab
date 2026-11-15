# Avaliação de frameworks: motor + camada de gestão da LEIA (P2)

- **Bead:** leia-lab-1g1.2 (épico leia-lab-1g1). Gate humano: leia-lab-1g1.3.
- **Data da pesquisa:** 2026-11-15. Preços, planos e páginas mudam; tudo abaixo vale para essa data.
- **Escopo:** pesquisa citada de 5 candidatos e recomendação de 2 finalistas para protótipos descartáveis. **Não** decide o framework (isso é o ADR-0002).
- **Convenção:** **[F]** = fato observado em fonte primária (citada); **[I]** = inferência minha; **[R]** = recomendação. "Não encontrado" = li as páginas indicadas e a informação não estava lá; não significa que não exista.

## 1. Resumo e recomendação

**Finalistas recomendados**

1. **Finalista A: LangGraph (motor de `master`) + LangSmith (SaaS).** Menor reescrita; um fornecedor cobre rastreio, hub de prompts, datasets/avaliações e Studio. Gestão de matriz de riscos, temas e base normativa continua a construir.
2. **Finalista B: Langfuse + Directus, motor-agnóstico (protótipo sobre o shell/pydantic-ai do acornworm).** Langfuse cobre rastreio, prompts e avaliação (núcleo MIT, self-host possível); Directus dá uma tela CRUD pronta sobre as tabelas de domínio (tipos de minuta, matriz, temas, base normativa). Como o Langfuse tem integração com LangGraph **e** pydantic-ai, esse par não prende a escolha do motor (Q5).

**Descartados:** Langflow (RBAC ausente no OSS, histórico de falhas críticas, volta à origem); pydantic-ai + Logfire como *par* (ótimo motor, gestão mais fraca: self-host só Enterprise, gestão de prompts não confirmada). O pydantic-ai segue vivo como **motor** dentro do finalista B.

**Achado que muda o desenho (vale para qualquer finalista) [F+I]:** nenhuma ferramenta de observabilidade cumpre sozinha o Q8 ("trilha auditável por análise: o que cada passo decidiu e por quê"). Retenção de traços é limitada por plano (LangSmith: 14 dias base / 180 estendido; Langfuse Cloud: janela de 30 dias a 3 anos) e nenhuma delas registra, por si só, *qual versão da matriz de riscos* e *quais normas* alimentaram a decisão. Recomendo que a **trilha-de-registro seja uma tabela própria no Postgres** (passo, entrada mascarada, decisão, pontuação, versão da matriz/prompt, normas citadas) e que a ferramenta de rastreio seja a **vista de depuração**, não a fonte da auditoria. Isso reduz o peso da escolha da ferramenta e é o que os protótipos devem provar.

## 2. O que já existe (mapeamento de código, somente leitura)

**Estados analisados (SHAs fixos):**

- `master`: `c57df533546061a5c55270161a774006aea15bda` (publicado).
- acornworm: checkout local `C:/Users/Vitor/dev/leia-lab/acornworm`, ramo `buhlerr/resume-previous-work-session`, HEAD local `40e2732f4396970652949903cfb335ff1c2e9c11` (commit `wip: preserve config admin UI and runtime work`). **Parte deste estado não está publicada:** o ramo remoto está em `45b6d19fe3feaa5688d8cba7d2807acaf85e70fe` e o HEAD local tem 1 commit à frente. Só existem no commit local (não em `origin`): `src/db/config_admin.py`, `src/ui/pages/1_Administracao.py`, `src/ui/runtime.py` e `tests/test_config_admin.py`, mais alterações em `src/ui/app.py` (diff `45b6d19..40e2732`). O `.delegateignore` **está publicado** no ramo do acornworm (`45b6d19`); só não está em `master`. A linha *UI* e o que depende dela (reaproveitar a tela de administração no protótipo A) descrevem estado **local/não publicado**, que não pode ser aberto por quem só tem o remoto. Os demais arquivos citados (`schema_config.sql`, `config_repo.py`, `pipeline.py`, `classifier.py`, `config.py`) existem em `45b6d19`.

| Critério | `master` (src/graphs, LangGraph) | acornworm (branch `buhlerr/resume-previous-work-session`, pydantic-ai) |
|---|---|---|
| Tipos de minuta | Fixo no código: `classificar` decide `locacao_residencial` vs `nao_suportado` (`analyze_minuta_graph.py`, `_Q_TIPO`). Sem conceito de tipo configurável. | **Sim, em banco**: `minuta_types` e `minuta_reports` (`schema_config.sql`), com prompt, modelo e ordem de execução por relatório. |
| Prompts | Constantes no código (`SISTEMA_REDIGIR`, perguntas Jev). | **Em banco**; "mudar prompt é um UPDATE". |
| Matriz de riscos / temas | Em código: `DEFAULT_RISCOS`, `DEFAULT_TEMAS`, `DEFAULT_TEMA_MAP` + `load_risk_matrix` (`minuta_rules.py`). A matriz real "ainda não validada por advogado". Criticidade vem da matriz, não do LLM (Q6). | **Não existe** matriz nem temas. |
| Base normativa (ingestão) | `ingest_graph` + `kb_docs`/`kb_chunks` (pgvector + tsvector), `hybrid_search_rrf`. | Mesma base (`schema.sql`, `rag/`) + extração isolada de arquivos (`ingest/isolated.py`). |
| Mascaramento de PII | **Sim**: `ingest/masking.py`, nó `mascarar` antes de qualquer chamada externa. | **Não tem.** |
| Histórico de análises | **Não persiste.** O resultado vive no estado do grafo. | **Não persiste** (`AnalysisResult` em memória; sem tabela de análises). |
| Trilha por passo | O estado carrega boa parte da trilha (`clausulas[].checks`, `candidatas`, `normas`, `analise_bruta`, `stats`) mas é descartado ao fim da execução. | Só `ReportResult` (status, modelo, tokens). Nada sobre "por quê". |
| UI | Nenhuma. | Streamlit (`src/ui/app.py`) + página de administração (**sem autenticação**, documentado no próprio arquivo). **A página de administração só existe no commit local `40e2732`, não publicado.** |
| Endurecimento | Texto de minuta fora de logs/exceções; semáforo global de chamadas externas. | Injeção de prompt, extração isolada, provedor de LLM configurável: **OpenRouter** com retenção zero opcional (`ZERO_RETENTION_PROVIDER = {zdr: true, data_collection: deny}`, `src/config.py`); **DeepSeek (o `CHAT_PROVIDER` padrão) é API direta, sem opção de retenção zero**, e a UI avisa para usar só minutas fictícias com ele; ~107 testes (contagem informada pelo humano, não reexecutada). |

**Achado de privacidade [F, código]:** em `master`, `read_file` grava `raw_text` no estado e `mascarar` o lê dali (`analyze_minuta_graph.py:166-182`). Qualquer ferramenta que capture o estado/entradas de cada nó (LangSmith, Langfuse) enviaria o **texto cru** a um terceiro, contrariando o Q2 ("mascarar antes de toda chamada externa"). Todo protótipo precisa resolver isso (retirar `raw_text` do estado ou aplicar máscara no export do traço).

**Mesmo risco, fora das ferramentas de rastreio [I]:** o *checkpointer* do LangGraph grava o estado completo a cada passo. Com `raw_text` no estado, o texto cru ficaria nos checkpoints do Postgres, em `get_state_history` e no estado de *thread* de um grafo implantado (Agent Server/Studio), sem chamada externa explícita. Retirar `raw_text` do estado cobre todos esses casos; mascarar só o export de traços não cobre.

## 3. Tabela comparativa

Legenda: ● nativo / ◐ parcial ou com ressalva / ○ a construir.

| | 1. LangGraph + LangSmith | 2. pydantic-ai + Logfire | 3. Langflow | 4. Langfuse (+ motor) | 5. Directus (+ motor) |
|---|---|---|---|---|---|
| **Q8: trilha por análise** | ◐ traços + histórico de checkpoints (Postgres); retenção limitada; registro de domínio a construir | ◐ spans via OTel; retenção 30/90 dias; registro de domínio a construir | ◐ mensagens/execução no banco do Langflow; sem trilha por passo confirmada | ◐ traços (janela 30d–3a); audit log de ações de usuário só Enterprise | ○ log de atividade sem *deltas*; admin pode editar entradas |
| Tipos de minuta + prompts | ◐ Prompt Hub com versões/tags, editável por UI; "tipo" a construir | ○ prompts em código; "gerir prompts" citado, não confirmado | ◐ no próprio fluxo | ◐ prompts com versões/labels, editáveis por não devs; "tipo" a construir | ● CRUD sobre tabelas `minuta_types`/`minuta_reports` (já existem no acornworm) |
| Matriz de riscos + temas | ○ | ○ | ○ | ○ | ● CRUD (relações a configurar no Directus) |
| Base normativa (ingestão) | ○ | ○ | ◐ componentes de KB próprios | ○ | ◐ lista/edita `kb_docs`, upload e gatilho por Flow; ingestão continua nossa; colunas `vector` não confirmadas |
| Histórico de análises | ◐ Studio: threads, *time travel* | ◐ Live view | ◐ "View chat history" | ◐ lista de traços/sessões | ● vista sobre a tabela de análises (se existir) |
| Admin por não devs | ◐ (prompts e datasets sim; resto não) | ◐ datasets editáveis na UI; resto não | ● UI visual, mas RBAC ausente no OSS | ◐ prompts/experimentos sim; resto não | ● é o ponto forte |
| Avaliação com gold set | ● datasets + `evaluate()` + "Run experiment" no Studio | ● `pydantic-evals` (código) + datasets hospedados no Logfire | ○ | ● datasets, experimentos via UI, LLM-as-judge, filas de anotação (inclusive OSS) | ○ |
| Hospedagem | SaaS (US/EU/APAC); self-host só Enterprise | SaaS (EU/US); self-host só Enterprise | Self-host; SaaS não encontrado | SaaS (US/EU/JP/HIPAA) **e** self-host OSS | Cloud ou self-host |
| Licença | LangGraph MIT; LangSmith proprietário | pydantic-ai e logfire (SDK) MIT; servidor/UI não confirmado | MIT | MIT exceto pastas `ee` | MSCL (fonte disponível, limites de faturamento) |
| Custo (lista) | Plus US$ 39/assento/mês + traços (preço por traço **não encontrado**) | Team US$ 49/mês (5 assentos) | grátis (infra) | Core US$ 29, Pro US$ 199, Enterprise US$ 2.499/mês; self-host grátis | Cloud Core US$ 89/mês (anual); grátis se < US$ 5 mi e < 50 pessoas |
| Migração de `master` | **baixa** (variáveis de ambiente + máscara) | **alta** (reescrever 420 linhas de grafo) | alta (voltar ao ponto de partida) | baixa-média (callback do LangGraph) | n/a (camada separada, baixa) |
| Migração do acornworm | alta (reescrever pipeline) | **nenhuma** (já é pydantic-ai); falta matriz, máscara, trilha | alta | baixa (`instrument_all`) | baixa (tabelas já existem) |
| Maturidade/risco | alta | média-alta | **risco**: 5 avisos críticos na 1ª página de 4 em 2026 | alta | alta |

## 4. Achados por candidato

### 4.1 LangGraph + LangSmith

- **Trilha.** O LangGraph persiste *checkpoints* e expõe `get_state_history`, que lista os estados por *thread* em ordem cronológica, com `writes` de cada passo, e permite reexecutar a partir de um checkpoint (re-executa chamadas de LLM, então o resultado pode divergir). [F] <https://docs.langchain.com/oss/python/langgraph/use-time-travel>, <https://docs.langchain.com/oss/python/langgraph/checkpointers>. Isso é a melhor base nativa para "o que cada passo decidiu", mas é histórico de **estado**, não de **razões**; as razões (nota, corte, norma) já estão no nosso estado e precisam ser gravadas por nós. [I]
- **Studio / edição de prompts.** O Studio roda grafos implantados na LangSmith ou localmente via Agent Server; tem modo Chat "útil para usuários de negócio", edição de prompt direto no nó e "Run experiment" sobre dataset sem código. [F] <https://docs.langchain.com/langsmith/studio>, <https://docs.langchain.com/langsmith/observability-studio.md>. Disponibilidade por plano: não confirmada.
- **Prompt Hub.** Commits com *diff*, tags `staging`/`production`, promoção e *rollback* pela UI; "prompts frequentemente precisam ser editados por quem não é engenheiro". [F] <https://docs.langchain.com/langsmith/manage-prompts.md>, <https://docs.langchain.com/langsmith/prompt-engineering>.
- **Avaliação.** `evaluate()` sobre datasets versionados (`as_of`), filtro por metadados; regras online e filas de anotação. [F] <https://docs.langchain.com/langsmith/manage-datasets>. Datasets têm retenção indefinida. [F] <https://docs.langchain.com/langsmith/usage-and-billing.md>
- **Risco de privacidade no estado [I]:** o estado persistido pelo checkpointer e o estado de *thread* no Agent Server contêm tudo o que está no estado do grafo; com o `raw_text` atual de `master` isso guarda o texto cru (ver seção 2). Mitigação a testar: tirar `raw_text` do estado (ler e mascarar no mesmo nó).
- **Hospedagem/licença/custo.** Plus: US$ 39/assento, 10 mil traços base, 1 Agent Server serverless pequeno; Enterprise: self-host/híbrido. Retenção: 14 dias (base), 180 dias (estendida, taxa **não informada**). Regiões: GCP US/EU/APAC, AWS US, Azure US; SOC 2 Tipo 2, HIPAA, GDPR; LGPD **não encontrado**; sem região no Brasil. LangGraph é MIT. [F] <https://www.langchain.com/pricing>, <https://docs.langchain.com/langsmith/cloud.md>, <https://docs.langchain.com/langsmith/regions-faq>, <https://github.com/langchain-ai/langgraph>. Self-host exige plano Enterprise e chave de licença. [F] <https://docs.langchain.com/langsmith/self-hosted>
- **Mascaramento.** Existem `LANGSMITH_HIDE_INPUTS/OUTPUTS/METADATA`, `create_anonymizer` (regex/função) e `process_inputs/outputs`; o anonimizador é ignorado quando `HIDE_INPUTS` está ligado; "redação não é controle de acesso". [F] <https://docs.langchain.com/langsmith/mask-inputs-outputs.md>. Aplicação a nós do LangGraph: sem exemplo explícito. [I] deve funcionar por ser nível de cliente; **o protótipo tem de provar**.
- **Lock-in.** Ferramentas de gestão (Hub, Studio, avaliações) são proprietárias; o código do grafo permanece MIT. [I]

### 4.2 pydantic-ai + Logfire

- **Motor.** `pydantic-graph` oferece máquina de estados tipada (sem dependência do pydantic-ai); persistência/retomada exige "StepPersistence" do Pydantic AI Harness; execução durável via Temporal/DBOS/etc. [F] <https://pydantic.dev/docs/ai/graph/graph/>, <https://pydantic.dev/docs/ai/integrations/durable_execution/overview/>. "Durabilidade não é armazenamento." [F, mesma página]
- **Avaliação.** `pydantic-evals`, "code-first"; datasets também hospedados no Logfire, **editáveis na UI** por um colega, com ligação ao traço de origem. [F] <https://pydantic.dev/docs/ai/evals/evals/>, <https://pydantic.dev/docs/logfire/evaluate/manage-datasets/>. Editar prompts na UI do Logfire: **não confirmado** (só a frase "manage prompts" na visão geral). [F] <https://pydantic.dev/docs/logfire/>
- **Planos.** Personal grátis (10 mi registros, 30 dias); Team US$ 49/mês (5 assentos, 30 dias, anotações humanas); Growth US$ 249/mês (90 dias, BAA); Enterprise: self-host, log de auditoria via API, redação/DLP (add-on). Convidados são somente leitura. [F] <https://pydantic.dev/pricing>. Self-host só Enterprise, em Kubernetes. [F] <https://pydantic.dev/docs/logfire/deploy/enterprise/>
- **Conteúdo.** `logfire.instrument_pydantic_ai(include_content=False)` exclui prompts/respostas dos spans (a limpeza padrão não atua nas mensagens de LLM). [F] <https://pydantic.dev/docs/logfire/instrument/python/scrubbing/> (via Context7).
- **Licença.** pydantic-ai e logfire (SDK): MIT. Se o servidor/UI é aberto: não confirmado. [F] <https://github.com/pydantic/pydantic-ai/blob/main/LICENSE>, <https://github.com/pydantic/logfire/blob/main/LICENSE>
- **Leitura.** Bom como **motor** (já é o acornworm). Como camada de gestão fica atrás: nada para matriz/temas/base normativa e nenhuma tela de domínio. [I]

### 4.3 Langflow

- MIT; versões de fluxo salvas no banco, restauráveis (Version History); tempo de execução sem UI via `lfx run/serve`. [F] <https://github.com/langflow-ai/langflow>, <https://docs.langflow.org/concepts-flows>, <https://docs.langflow.org/lfx-overview>
- **RBAC:** "exige um plugin de autorização registrado, que o Langflow não inclui"; sem ele, todo usuário autenticado pode tudo. [F] <https://docs.langflow.org/authentication-overview>. Isso falha o requisito de administração segura por não devs. [I]
- **Observabilidade:** a exportação OTel "não é rastreio de LLM" (um span `flow.execute` por execução); rastreio fino exige integração com Langfuse/LangSmith. [F] <https://docs.langflow.org/observability-opentelemetry>
- **Segurança:** na 1ª de 4 páginas de avisos há 5 críticos em 2026, incluindo RCE sem autenticação (mar/2026) e RCE autenticada via MCP (set/2026). [F] <https://github.com/langflow-ai/langflow/security/advisories>. Páginas 2–4 não lidas.
- **Leitura.** Não resolve o Q8, reintroduz o ponto de partida da migração e tem superfície de ataque grande para dados de contrato. [R] descartar.

### 4.4 Langfuse (+ motor)

- **Licença/self-host.** MIT, exceto pastas `ee`; recursos pagos de self-host: auditoria, SCIM, RBAC por projeto, retenção, mascaramento no servidor. Self-host: web + worker + PostgreSQL + ClickHouse + Redis + S3. [F] <https://langfuse.com/docs/open-source>, <https://langfuse.com/pricing-self-host>. Esforço operacional não medido nas páginas. [I] mais pesado que o stack atual.
- **Prompts.** "Membros não técnicos atualizam direto na UI"; versões e labels (`production`); rótulos protegidos só em Pro+Teams/Enterprise. [F] <https://langfuse.com/docs/prompt-management/overview>, <https://langfuse.com/docs/prompt-management/features/prompt-version-control> (via Context7).
- **Avaliação.** Datasets, experimentos via UI (prompt + dataset + conexão LLM, sem SDK), LLM-as-judge e filas de anotação no OSS; comparação lado a lado. [F] <https://langfuse.com/docs/evaluation/experiments/experiments-via-ui>, <https://langfuse.com/pricing-self-host>
- **Papéis.** Owner/Admin/Member/Viewer; criar prompts, datasets e avaliadores exige no mínimo Member; papéis por projeto só Enterprise/Teams. [F] <https://langfuse.com/docs/administration/rbac>
- **Auditoria.** Logs de auditoria (inclui prompts, datasets, scores, com estado antes/depois) só em Cloud Enterprise e self-host Enterprise. [F] <https://langfuse.com/docs/administration/audit-logs>. No OSS/Core/Pro, sem auditoria de quem alterou o quê além do versionamento de prompts. [I]
- **Planos e regiões.** Core US$ 29 (100 mil unidades, 90 dias), Pro US$ 199 (3 anos), Enterprise US$ 2.499; unidade = traço, observação ou score; regiões US/EU/JP/HIPAA; SOC 2 II/ISO 27001 (Pro+). [F] <https://langfuse.com/pricing>, <https://langfuse.com/security>. Cada análise tem dezenas a centenas de observações (um `jev()` por cláusula e risco). [I] o consumo de unidades precisa ser medido no protótipo.
- **Mascaramento.** `mask_otel_spans` (Python) no export; se falhar, **descarta o lote inteiro**. [F] <https://langfuse.com/docs/observability/features/masking>
- **Integrações.** LangGraph (`CallbackHandler`) e pydantic-ai (`Agent.instrument_all()`, OTel). [F] <https://langfuse.com/integrations/frameworks/langgraph>, <https://langfuse.com/integrations/frameworks/pydantic-ai>

### 4.5 Directus (+ motor)

- **Licença: não é BSL.** MSCL 1.0 (fonte disponível, derivada da Fair Core License); gratuito para organizações com receita anual < US$ 5 mi e < 50 funcionários; uso comercial concorrente é vedado; converte para GPL-3.0 após 4 anos. [F] <https://github.com/directus/directus>, <https://directus.com/license>. **Pergunta aberta para o humano:** a organização se enquadra? [I] provavelmente, mas não verifiquei.
- **Preços (Cloud).** Core US$ 89/mês anual (3 assentos, 25 coleções, 5 Flows); Team US$ 588/mês anual; a página é inconsistente (FAQ cita US$ 499/US$ 599). Self-host em todos os níveis. [F] <https://directus.com/pricing>
- **Banco existente.** Introspecta tabelas e relações existentes; metadados de interface precisam ser configurados; relações ausentes no banco precisam ser criadas no Directus. [F] <https://directus.com/docs/guides/data-model/collections> (via Context7)
- **Permissões.** Políticas aditivas, permissões por campo e por ação. [F] <https://directus.com/docs/guides/auth/access-control>
- **Atividade/auditoria.** Registra Create/Update/Delete/Comment/Login com usuário, data, IP, coleção e item, **sem valores antes/depois**; só vê o que passa pela plataforma; **admins podem modificar itens de atividade** em coleções não-sistema. [F] <https://directus.com/docs/guides/auth/accountability>. Revisões por item: **não encontrado** nas páginas lidas. Logo **não serve como trilha de auditoria** do Q8; serve como CRUD. [I]
- **Tipos.** JSON e CSV existem; arrays Postgres e `vector` **não aparecem**. [F] <https://directus.com/docs/guides/data-model/fields>. Risco para `kb_chunks.embedding`; mitigação: expor só `kb_docs`. [I]
- **Flows** disparam por evento, agenda ou webhook. [F] <https://directus.com/docs/>. Limites por plano (5 no Core).

## 5. Contra o Q8 e os critérios de desempate

| Critério | A: LangGraph + LangSmith | B: Langfuse + Directus (+ motor) |
|---|---|---|
| Trilha auditável (hard) | Traço + checkpoints; **registro Postgres próprio necessário** | Traço + **registro Postgres próprio necessário**; auditoria de ações de usuário só em Enterprise |
| Admin sem desenvolvedor | Prompts e datasets sim; matriz/temas/base normativa **não** (a construir) | Prompts (Langfuse) + matriz/temas/tipos/base (Directus): **cobre os 4 pontos** |
| Avaliação com gold set | Nativa, inclusive no Studio | Nativa, inclusive via UI, também no OSS |
| Pouca reescrita | **Melhor**: `master` fica quase intacto | Tabelas do acornworm reaproveitadas; motor depende da escolha |
| Hospedagem / dados | SaaS apenas (self-host Enterprise) | SaaS ou self-host grátis; mais infraestrutura |
| Privacidade (Q2) | Máscara no cliente; terceiro recebe traços | Idem; self-host mantém tudo local |

Decisões do usuário usadas: Q2 (mascarar antes de qualquer chamada externa; traços para SaaS contam como chamada externa [I]), Q6 (criticidade da matriz, não do LLM), Q7 (SaaS aceitável), Q8 (único requisito duro), Q10 (nenhuma mudança de código antes do ADR-0002).

## 6. O que cada protótipo deve demonstrar

Protótipos descartáveis, fora do caminho principal (Q10). Usar o mesmo conjunto: 2–3 minutas já mascaradas de `leia-minutas-teste-mascaradas` e um gold set mínimo (≥10 cláusulas com riscos esperados).

**Comum aos dois**
1. **Trilha por análise reconstruível**: dado só um `analysis_id`, mostrar por passo: entrada mascarada, decisão, nota/corte, normas citadas, **versão da matriz e do prompt**. Registro em Postgres próprio; ferramenta como vista complementar.
2. **Nenhum texto cru fora do processo**: provar (inspecionando o que chega ao serviço de traços) que não vai nome/CPF; tratar o `raw_text` do estado de `master`.
3. **Gold set**: rodar o conjunto, ver nota por risco esperado vs. detectado e comparar duas versões de prompt ou de matriz. O avaliador será código (compara ids de risco).
4. **Tipo de minuta como dado**: adicionar um segundo tipo (ex.: stub) sem mexer em código.

**Específico do A (LangGraph + LangSmith)**
- Grafo de `master` com Postgres checkpointer e `get_state_history`; o Studio abre o grafo e permite editar um prompt e ver o efeito.
- **`raw_text` ausente do estado persistido**: após uma análise, varrer as tabelas do checkpointer, a saída de `get_state_history` e o estado de *thread* do grafo implantado (Agent Server local/Studio) e provar que não há nome/CPF nem o texto cru (risco descrito em 2 e 4.1).
- Prompt Hub: alterar prompt por um não-dev e a próxima execução usar a nova versão (`production`).
- Anonimizador funcionando em nós do LangGraph; medir traços e custo por análise (preço por traço não encontrado).
- Esforço para construir a tela de matriz/temas/base (Streamlit do acornworm reaproveitado, com autenticação; atenção: a página de administração existe só no commit local `40e2732`, ainda não publicado).

**Específico do B (Langfuse + Directus)**
- Directus sobre o Postgres: CRUD de `minuta_types`, `minuta_reports`, matriz e temas por um não-dev, com papéis; ver se `kb_docs` aparece e o que ocorre com colunas `vector`/arrays.
- Mudança feita no Directus vale na próxima análise (sem cache).
- Langfuse (self-host via Docker Compose e/ou Cloud): prompt editado na UI; experimento via UI sobre o gold set; medir unidades por análise contra o limite do plano; custo/esforço de operar PostgreSQL + ClickHouse + Redis + S3.
- Rodar o rastreio nos **dois motores** (callback LangGraph e `instrument_all` do pydantic-ai) para alimentar o ADR-0002 sem decidir o motor antes.
- Registrar o que a auditoria nativa (Enterprise) faria a mais e se o registro próprio basta.

**Critérios de saída (propostos):** nota por (a) trilha reconstruível, (b) não-dev edita prompt/matriz/tema sem ajuda, (c) gold set comparando versões, (d) horas de reescrita, (e) custo mensal estimado.

## 7. Perguntas abertas que podem mudar a recomendação

1. **Preço por traço e taxa da retenção estendida da LangSmith**: não encontrados. Pode inverter custo A × B.
2. **Elegibilidade ao Directus** (MSCL): a organização cabe nos limites de receita/funcionários?
3. **Directus × colunas `vector`/arrays** e revisões por item: não confirmados.
4. **Langfuse auto-hospedado**: esforço real de operação (ClickHouse) não medido.
5. **Logfire**: edição de prompts na UI e redação de conteúdo fora do Enterprise não confirmadas; se confirmadas, melhora o par pydantic-ai + Logfire.
6. **Residência de dados**: nenhuma das nuvens tem região no Brasil; LGPD não aparece nas páginas lidas (Langfuse: GDPR/DPA; LangSmith: GDPR/DPA). Decisão de tolerância é do humano (Q7 aceita SaaS).
7. **Langflow**: páginas 2–4 de avisos e a documentação de deployments não lidas; não alteram o descarte.
8. **Armazenamento da trilha como "auditável"**: se auditoria exigir imutabilidade, avaliar *append-only* no Postgres; o log de atividade do Directus é editável por admin.

## 8. Limites desta pesquisa

- Leitura de páginas oficiais em 2026-11-15; Context7 (via Composio) para documentação de bibliotecas, páginas web para preços/licenças. Alguns links redirecionaram (`ai.pydantic.dev` → `pydantic.dev/docs/ai`, `docs.directus.io` → `directus.com/docs`).
- Sem teste prático: tudo é documentação, nenhum comportamento foi executado. Valores em dólar são preço de lista.
- `.delegateignore` não está em `master` (só no ramo do acornworm, publicado em `45b6d19`), então não houve delegação ao Command Code; o mapeamento de código foi feito diretamente.
- Candidato trocado: **nenhum**. O par Directus foi avaliado junto ao Langfuse por serem complementares (um cobre domínio, o outro, LLM-ops).
