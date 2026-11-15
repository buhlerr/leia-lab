# Avaliação de frameworks: motor + camada de gestão da LEIA (P2)

- **Bead:** leia-lab-1g1.2 (épico leia-lab-1g1). Gate humano: leia-lab-1g1.3.
- **Data da pesquisa:** 2026-11-15. Preços, planos e páginas mudam; tudo abaixo vale para essa data.
- **Escopo:** pesquisa citada de 5 candidatos e recomendação de 2 finalistas para protótipos descartáveis. **Não** decide o framework (isso é o ADR-0002).
- **Convenção:** **[F]** = fato observado em fonte primária (citada); **[I]** = inferência minha; **[R]** = recomendação. "Não encontrado" = li as páginas indicadas e a informação não estava lá; não significa que não exista.

## 1. Resumo e recomendação

> **Atualização (adendo B2b, leia-lab-1g1.8):** depois de comparar também ferramentas de gestão de dados de domínio (seção 9), a recomendação passa a ser expressa como **combinações** motor + rastreio + gestão. Prototipar **C1 = LangGraph + LangSmith + Django Admin** e **C2 = LangGraph + Langfuse + Directus** (detalhes, ranking e provas em 9.6 e 9.7). A lista abaixo é a versão inicial e fica como histórico.

**Finalistas recomendados (versão inicial)**

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
- **Atividade/auditoria.** Registra Create/Update/Delete/Comment/Login com usuário, data, IP, coleção e item, **sem valores antes/depois**; só vê o que passa pela plataforma; **admins podem modificar itens de atividade** em coleções não-sistema. [F] <https://directus.com/docs/guides/auth/accountability>. Revisões por item (dados + *delta*) existem, ver 9.2 (adendo B2b). O log de atividade sozinho **não serve como trilha de auditoria** do Q8. [I]
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

> **Atualizado pelo adendo B2b (leia-lab-1g1.8):** os dois protótipos passam a ser as **combinações** motor + rastreio + gestão **C1** e **C2** da seção 9.6, ambas sobre o motor LangGraph de `master` (o motor fica como variável controlada; pydantic-ai entra só como checagem de instrumentação). Os itens "Comum" abaixo continuam valendo; os itens específicos foram reorganizados em C1/C2 e ampliados em 9.7. As antigas "A" e "B" abaixo são mantidas apenas como histórico do que cada ferramenta de rastreio deve provar.

**Histórico: específico do rastreio LangSmith (antigo A)**
- Grafo de `master` com Postgres checkpointer e `get_state_history`; o Studio abre o grafo e permite editar um prompt e ver o efeito.
- **`raw_text` ausente do estado persistido**: após uma análise, varrer as tabelas do checkpointer, a saída de `get_state_history` e o estado de *thread* do grafo implantado (Agent Server local/Studio) e provar que não há nome/CPF nem o texto cru (risco descrito em 2 e 4.1).
- Prompt Hub: alterar prompt por um não-dev e a próxima execução usar a nova versão (`production`).
- Anonimizador funcionando em nós do LangGraph; medir traços e custo por análise (preço por traço não encontrado).
- Esforço para construir a tela de matriz/temas/base (Streamlit do acornworm reaproveitado, com autenticação; atenção: a página de administração existe só no commit local `40e2732`, ainda não publicado).

**Histórico: específico de Langfuse + Directus (antigo B)**
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

## 9. Adendo B2b: camada de gestão dos dados de domínio (leia-lab-1g1.8)

Pedido do usuário: nenhum framework de LLM gerencia os dados de domínio (matriz de riscos, temas, tipos de minuta, base normativa) e só o Directus tinha sido avaliado nessa categoria. Esta seção compara ferramentas de gestão e atualiza a recomendação, agora como **combinações** motor + rastreio + gestão. Leitura de páginas oficiais em 2026-11-15; mesma convenção **[F]/[I]/[R]** do cabeçalho. Sem delegação ao Command Code: o `.delegateignore` ainda não está em `master`.

Critérios: (a) CRUD por não desenvolvedores com papéis/login; (b) **histórico/versionamento das linhas de domínio** (para uma análise registrar qual versão da matriz decidiu; liga ao Q8, e importa se o histórico é imutável ou editável por admin); (c) funciona direto sobre as tabelas Postgres existentes, com relações e colunas vector/array; (d) licença e custo; (e) esforço de self-host; (f) encaixe com a stack Python e carga de manutenção.

### 9.1 Conclusão principal sobre versionamento (critério b)

**Nenhuma ferramenta garante sozinha um histórico imutável das linhas de domínio [F+I]:**

- Directus: revisões guardam cópia do item e *delta*, mas só para mudanças que passam pela plataforma, e a própria documentação manda "remover periodicamente" dados de `directus_revisions`. A leitura das revisões fica restrita a admins/editores.
- Django + django-simple-history: guarda estado e `history_user` a cada gravação, mas só captura o que passa pelo ORM (não captura SQL cru, gatilhos ou outros serviços, nem `bulk_*`/`.update()` sem os helpers). Se o admin pode editar/apagar as linhas de histórico: **não encontrado** na documentação atual.
- NocoDB: histórico por registro é somente leitura ("não é possível editar ou apagar"), mas a retenção depende do plano e a auditoria do workspace é Scale+.
- Appsmith, ToolJet, Budibase: auditoria de eventos, não de valores de linha (Budibase: auditoria de linhas "não suportada" por padrão).

**[R] Projetar o versionamento fora da ferramenta de gestão**, em dois níveis. Isso torna a escolha da ferramenta de gestão menos crítica para o Q8:

1. **Snapshot por análise**: cada análise grava, no seu próprio registro, o `id` da versão da matriz/prompt e uma cópia (JSON + hash) das regras efetivamente usadas. A análise fica autossuficiente mesmo se a matriz mudar depois.
2. **Histórico *append-only* por gatilho no Postgres** nas tabelas de domínio (inserir em tabela de histórico a cada INSERT/UPDATE/DELETE; sem UPDATE/DELETE para os papéis da aplicação). Pega escritas de qualquer ferramenta, inclusive SQL manual. Vale como histórico oficial; o histórico nativo da ferramenta de gestão vira conveniência de UI.

### 9.2 Categoria 1: painéis de administração sobre o Postgres existente

Legenda: ● atende / ◐ parcial ou com ressalva / ○ não atende ou não encontrado.

| | Directus | Django Admin + simple-history | NocoDB | Appsmith | ToolJet | Budibase |
|---|---|---|---|---|---|---|
| (a) CRUD por não devs + papéis | ● políticas por coleção/campo | ◐ permissões add/change/delete/view **por modelo**, grupos; por campo exige código | ◐ papéis Owner/Creator/Editor/Commenter/Viewer; por campo só plano Business | ◐ telas **construídas à mão**; papéis customizados no Business | ◐ telas à mão; grupos; RLS só Enterprise | ◐ telas geradas das tabelas buscadas, ajustadas à mão |
| (b) histórico das linhas | ◐ revisões (dados + *delta*) só via plataforma; admin pode purgar | ◐ histórico com *diff* e usuário; só via ORM; editabilidade não confirmada | ◐ histórico por registro somente leitura; retenção por plano | ○ só eventos de auditoria (Business) | ○ só eventos de auditoria (Team) | ○ auditoria de linhas não suportada por padrão |
| (c) tabelas existentes, vector/array | ◐ introspecção; tipos desconhecidos **não documentado** | ◐ `inspectdb` gera modelos não gerenciados; tipo desconhecido vira `TextField` ("palpite"); `VectorField` via pgvector-python | ◐ conecta PG externo; flags de edição de dados/esquema; tipos **não encontrado** | ○ não encontrado | ○ não encontrado | ◐ "Fetch tables"; mapeamento de tipos **não encontrado**; relações só internas ao Budibase |
| (d) licença / custo | MSCL (fonte disponível; grátis < US$ 5 mi e < 50 pessoas); Cloud a partir de US$ 89/mês | BSD (Django e simple-history); sem custo | Sustainable Use License (uso interno OK); Comunidade grátis; Cloud Business US$ 24/assento (Plus **não** aceita banco externo) | Apache-2.0; Business US$ 15/usuário (até 99) | **AGPLv3**; Team US$ 199/construtor | GPLv3 geral, BSL em `/packages/pro`; Cloud a partir de US$ 299/mês |
| (e) self-host | Docker; tabelas `directus_*` **no mesmo banco** | Aplicação Django + tabelas próprias de auth/admin/histórico | 2 vCPU/2 GB mín.; banco de metadados próprio | Docker/K8s; mínimos não encontrados | Postgres 16 + Redis 7, x86 | CouchDB interno |
| (f) Python / manutenção | JS/Node; config majoritariamente sem código; Flows chamam HTTP | **Python**; ModelAdmin é código a manter, mas pequeno | JS; sem código | JS | JS | JS |

**Fontes por ferramenta [F]:**

- **Django Admin / simple-history:** `inspectdb` (modelos não gerenciados; tipos não mapeados viram `TextField` com comentário "guess") <https://docs.djangoproject.com/en/stable/ref/django-admin/#inspectdb>; permissões padrão <https://docs.djangoproject.com/en/stable/topics/auth/default/>; `LogEntry` registra só alterações feitas pelo admin e, na edição, a lista de campos editados, sem valores antigos/novos <https://docs.djangoproject.com/en/stable/ref/contrib/admin/#logentry-objects>; licença BSD <https://github.com/django/django/blob/main/LICENSE>; `VectorField` e `HnswIndex` <https://github.com/pgvector/pgvector-python>; simple-history (BSD-3, versão 3.13.0 de 2026-07-22; `history_user`, `diff_against`, revert no admin, limites de `bulk_*`/`F()`/escritas externas) <https://django-simple-history.readthedocs.io/en/latest/>, <https://django-simple-history.readthedocs.io/en/latest/common_issues.html>, <https://django-simple-history.readthedocs.io/en/latest/historical_model.html>, <https://django-simple-history.readthedocs.io/en/latest/admin.html>. Nada encontrado sobre simple-history com modelos `inspectdb`: o `HistoricalRecords` precisa ser declarado no modelo (escrito/editado à mão).
- **Directus:** revisões "criadas sempre que um item é atualizado", com cópia versionada completa e mudanças específicas <https://directus.com/docs/guides/data-model/collections>; API de revisões (`data` e `delta`; só leitura documentada) <https://directus.com/docs/api/revisions>; Content Versioning por coleção <https://directus.com/docs/guides/content/content-versioning> (limite por plano **não informado**; revisões/versionamento não aparecem como recurso de plano em <https://directus.com/pricing>); boas práticas (leitura de `directus_revisions` só para admins/editores) <https://directus.com/docs/guides/security/best-practices>; limites: sem chaves compostas nem tabelas virtuais por view <https://directus.com/docs/guides/data-model/collections>; Flows com gatilho de evento (ação não bloqueante) e operação "Request URL" (HTTP) <https://directus.com/docs/guides/flows/triggers>, <https://directus.com/docs/guides/flows/operations>; licença/preço <https://github.com/directus/directus>, <https://directus.com/license>, <https://directus.com/pricing>. **Correção ao 4.5:** a rodada anterior não achou revisões; elas existem. Mesmo assim o comportamento diante de `vector`, `text[]` e `tsvector` **não está documentado**.
- **NocoDB:** licença Sustainable Use v1.0, "uso interno do negócio" <https://github.com/nocodb/nocodb/blob/develop/LICENSE.md>; preços (Comunidade grátis; Plus US$ 12 sem banco externo; Business US$ 24 com 10 conexões externas e permissões por campo; Scale US$ 45 com RLS e auditoria) <https://nocodb.com/pricing>; papéis <https://nocodb.com/docs/product/collaboration/roles-and-permissions>; histórico por registro somente leitura, retenção por plano <https://nocodb.com/docs/product/tables/records/expand-record>; auditoria do workspace Scale+ <https://nocodb.com/docs/product/workspaces/workspace-audit>; conexão com Postgres externo, "Allow Data Edit" ligado e "Allow Schema Edit" desligado por padrão <https://nocodb.com/docs/product/integrations/data-sources/connect-to-data-source>; self-host <https://nocodb.com/docs/self-hosting>. Valores antes/depois no histórico e tratamento de `vector`/`tsvector`: **não encontrado**.
- **Appsmith:** Apache-2.0 <https://github.com/appsmithorg/appsmith/blob/release/LICENSE>; planos <https://www.appsmith.com/pricing>; auditoria de eventos (sem valores de linha) <https://docs.appsmith.com/advanced-concepts/audit-logs>.
- **ToolJet:** AGPLv3 <https://github.com/ToolJet/ToolJet/blob/develop/LICENSE>; planos (retenção de auditoria divergente: 14 dias na tabela de preços, 90 dias na doc) <https://www.tooljet.com/pricing>, <https://docs.tooljet.com/docs/security/audit-logs/>; requisitos <https://docs.tooljet.com/docs/setup/system-requirements/>.
- **Budibase:** GPLv3 geral, BSL em `/packages/pro` <https://github.com/Budibase/budibase/blob/master/LICENSE>; preços <https://budibase.com/pricing>; auditoria de linhas "não suportada" por padrão <https://docs.budibase.com/docs/audit-logs>; conexão SQL <https://docs.budibase.com/docs/sql-datasource>; CouchDB interno <https://docs.budibase.com/docs/data-sources>.

**Leitura [I/R]:**

- **Appsmith, ToolJet e Budibase não entram nos protótipos.** Todos exigem montar cada tela, nenhum tem histórico de linhas, e ToolJet (AGPL, US$ 199/construtor) e Budibase (CouchDB + licença mista) têm custo/licença menos favoráveis. Se algum for reconsiderado, Appsmith (Apache-2.0, US$ 15/usuário) é o melhor dos três.
- **NocoDB fica como reserva:** licença de fonte disponível, plano Plus não conecta banco externo, tratamento de tipos desconhecido; o histórico somente leitura é um ponto a favor.
- Colunas `vector`/`tsvector`: nenhuma documentação cobre. Mitigação: as ferramentas só precisam das tabelas de matriz, temas, tipos, relatórios/prompts e `kb_docs`; para `kb_chunks`, expor somente leitura **sem a coluna `embedding`**.
- Não troquei candidatos: as seis ferramentas do pedido foram avaliadas e a evidência já separa Directus e Django Admin como as duas melhores.

### 9.3 Categoria 2: gestão da base normativa (leis e jurisprudência)

| | Dify | RAGFlow | Manter `ingest_graph` + vista no painel |
|---|---|---|---|
| Licença | Apache-2.0 **modificada**: sem multi-tenant sem autorização por escrito; não remover logo/copyright do console | Apache-2.0 | n/a (código nosso) |
| Reaproveita nossas tabelas/pgvector? | Não encontrado: pgvector é opção de armazenamento (`PGVECTOR_*`), padrão Weaviate; sem mapear `kb_docs`/`kb_chunks` existentes. A API de conhecimento externo deixa o Dify **chamar** um endpoint `/retrieval` nosso, mas ingestão, edição de chunks e teste ficam no armazém do Dify | **Não**: armazém de documentos é Elasticsearch (padrão), Infinity, OceanBase, OpenSearch etc.; pgvector não é opção (Postgres só como banco de metadados) | Sim (é o que existe: `kb_docs`, `kb_chunks`, `hybrid_search_rrf`) |
| Inspeção/edição de chunks | Sim: adicionar/editar/desativar chunks (adicionar em lote só em planos pagos da nuvem); teste de recuperação na UI | "Visualização de chunks com intervenção humana" (README); detalhes **não verificados** | Vista somente leitura de `kb_chunks` no painel (sem `embedding`); edição de chunk **não** recomendada sem reindexação controlada |
| Reindexação | Troca do modelo de embedding no nível da KB; reindexar por documento: **não encontrado** | **Não verificado** | Ação que chama o `ingest_graph` (Django: *admin action* em Python; Directus: Flow com webhook) |
| Hospedagem | 2 núcleos/4 GiB mín.; stack próprio (api, worker, nginx, Weaviate…) | Recomendado 4 núcleos/16 GB/50 GB; Elasticsearch, MySQL, MinIO etc.; v1.0.0 lançada em 2026-11-06 | Já existe |
| Sobreposição | **Alta**: traz motor de workflows/agentes e observabilidade próprios | Média: foco em parsing/RAG; armazém próprio | Nenhuma |
| Português do Brasil | Não verificado | README em pt-BR; parsing/OCR em português **não encontrados** | Já tratado (`to_tsvector('portuguese')`) |

**Fontes [F]:** Dify: <https://github.com/langgenius/dify/blob/main/LICENSE>, <https://dify.ai/pricing>, <https://docs.dify.ai/en/cloud/use-dify/knowledge/readme.md>, <https://docs.dify.ai/en/cloud/use-dify/knowledge/manage-knowledge/maintain-knowledge-documents.md>, <https://docs.dify.ai/en/cloud/use-dify/knowledge/test-retrieval.md>, <https://docs.dify.ai/en/cloud/use-dify/knowledge/external-knowledge-api.md>, <https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose.md>; a lista de armazéns vetoriais veio de resumo automático parcial de <https://docs.dify.ai/en/self-host/deploy/configuration/environments.md> (tratar como secundária). RAGFlow: <https://github.com/infiniflow/ragflow>, <https://github.com/infiniflow/ragflow/blob/main/docker/.env>, <https://github.com/infiniflow/ragflow/blob/main/docker/README.md>; a documentação em ragflow.io/docs não renderizou, então a API de recuperação e a edição de chunks **não foram verificadas**.

**[R]** Não adotar Dify nem RAGFlow como camada de gestão da base normativa: nenhum reaproveita nossas tabelas, ambos criariam uma segunda fonte da verdade a reindexar, e o Dify ainda traria um motor concorrente. Manter o `ingest_graph` e dar a ele uma **vista de gestão** (lista de documentos, inspeção de chunks, ação de reindexar, envio de arquivo) no painel escolhido. Risco de privacidade menor aqui [I]: a base normativa contém leis e jurisprudência públicas, não minutas.

### 9.4 Categoria 3: revisão humana para o conjunto de referência (gold set)

| | Argilla | Label Studio | Langfuse (filas de anotação) |
|---|---|---|---|
| Licença | Apache-2.0 | Apache-2.0 (Community) | MIT (núcleo) |
| Custo | grátis (Docker/Hugging Face) | Community grátis; nuvem Starter US$ 99/mês + US$ 49/usuário extra | Cloud: 1 fila (Hobby), 3 (Core), ilimitadas (Pro+); self-host OSS: ilimitadas |
| Hospedagem | Docker com Elasticsearch | `pip`/Docker; Postgres/requisitos **não encontrado** | já faz parte do Langfuse |
| Papéis | owner/admin/annotator | Owner/Admin/Manager/Reviewer/Annotator (RBAC no Starter+) | RBAC de organização; papel mínimo para anotar **não informado** |
| Recursos relevantes | datasets, SDK Python, campos/perguntas customizáveis | LLM-as-a-judge e logs de atividade listados como Enterprise (mapeamento por edição ambíguo na página) | scores com *score configs* e comentários; "saídas corrigidas"; fila ligada ao traço |
| Ressalvas | manutenção atual **não verificada** | pricing movido para humansignal.com | escrever o valor esperado direto no item de dataset a partir da fila: **não encontrado** |

**Fontes [F]:** Argilla <https://docs.argilla.io/latest/>, <https://docs.argilla.io/latest/getting_started/how-to-deploy-argilla-with-docker/>, <https://docs.argilla.io/latest/how_to_guides/user/>; Label Studio <https://humansignal.com/pricing/>, <https://labelstud.io/>; Langfuse <https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues>, <https://langfuse.com/pricing>, <https://langfuse.com/pricing-self-host>.

**[R]** Não adicionar Argilla nem Label Studio agora. As filas do Langfuse (ou a fila de anotação da LangSmith, listada na página de preços) já cobrem "revisor aceita/rejeita/corrige" para um gold set pequeno; a revisão por cláusula também pode ser feita no painel de gestão se o gold set virar tabela de domínio. Reavaliar só se a revisão exigir fluxos que as filas não oferecem (a provar no protótipo).

### 9.5 O que o motor e o rastreio mudam (e o que não mudam)

O painel de gestão e o rastreio são **independentes do motor** (dados em Postgres; Langfuse e LangSmith aceitam LangGraph; Langfuse também aceita pydantic-ai). A evidência de reescrita (seção 2) favorece manter o motor de `master`: ele já tem Jev, matriz, mascaramento e validação, enquanto o acornworm não tem matriz, máscara nem trilha. Por isso os protótipos usam o **mesmo motor (LangGraph de `master`)** e variam só rastreio e gestão. A decisão A × B × C entre motores (Q5) fica para o ADR-0002; o pydantic-ai segue como checagem de instrumentação de 1 dia no Langfuse (já está no acornworm).

### 9.6 Combinações ranqueadas (motor + rastreio + gestão)

| # | Combinação | Por que | Principais riscos |
|---|---|---|---|
| **1 (prototipar C1)** | **LangGraph + LangSmith + Django Admin** (com histórico por gatilho + snapshot por análise) | Menor reescrita; tudo em Python; BSD, sem limite de faturamento; `inspectdb` + `ModelAdmin` pequenos; `diff_against` dá comparação de versões; Studio/Prompt Hub/datasets da LangSmith; ação de reindexar em Python | Admin é código a manter; permissões por modelo, não por campo; UI datada; LangSmith: SaaS (self-host só Enterprise), preço por traço não encontrado |
| **2 (prototipar C2)** | **LangGraph + Langfuse + Directus** | Gestão por configuração (papéis por campo, revisões com *delta*, Flows com webhook para reindexar); Langfuse MIT, pode ser hospedado por nós, filas de anotação ilimitadas no self-host | Licença MSCL (elegibilidade a confirmar); revisões purgáveis por admin; `vector`/arrays não documentados; Langfuse self-host pesado (ClickHouse + Redis + S3); Cloud Core limita 25 coleções |
| 3 (não prototipar; sai do cruzamento) | LangGraph + Langfuse + Django Admin | Combina licenças abertas (MIT + BSD) | Mesmos riscos do Django; resultado inferível dos protótipos 1 e 2 |
| 4 | LangGraph + LangSmith + NocoDB | Histórico por registro somente leitura | Licença de fonte disponível; Plus não conecta banco externo; tipos desconhecidos; retenção por plano |
| 5 | pydantic-ai (acornworm) + Langfuse + Django/Directus | Zero migração do acornworm | Reconstruir matriz, mascaramento e trilha; só se o G1 escolher o motor B |
| fora | Qualquer motor + Appsmith/ToolJet/Budibase; Dify; RAGFlow; Langflow | Sem histórico de linhas / telas à mão / sobreposição / segurança | ver 9.2, 9.3 e 4.3 |

**Nota [I]:** a diferença entre as combinações 1 e 2 é **pequena** e vem de licença, stack e custo de manutenção, não de superioridade funcional comprovada. Como painel e rastreio são independentes, o protótipo pode apontar Django Admin **e** Directus para o mesmo esquema e as duas ferramentas de rastreio para o mesmo grafo, comparando cada camada separadamente a custo marginal; a combinação 3 sai então quase de graça.

### 9.7 O que cada protótipo deve demonstrar (atualiza a seção 6)

**Comum a C1 e C2**
1. **Versionamento do Q8**: uma análise antiga continua mostrando a matriz/prompt que a decidiu depois de a matriz mudar (snapshot por análise), e o histórico oficial vem do gatilho *append-only*. Provar também uma escrita direta por `psql` (a ferramenta de gestão **não** a vê, o gatilho sim) e uma tentativa de apagar/editar histórico por um admin da ferramenta.
2. **Edição por não dev**: alguém sem acesso a código muda um risco, um tema e um prompt de relatório, e a **próxima** análise usa a nova versão, sem implantação.
3. **Tabelas existentes**: a ferramenta lê/edita matriz, temas, tipos, relatórios e `kb_docs` sem mover dados; mostrar o que acontece com `kb_chunks` (colunas `vector`, `tsvector`) e confirmar que só se expõe sem `embedding`.
4. **Base normativa**: lista de documentos, inspeção de chunks (somente leitura), envio de arquivo e **reindexação acionada pela ferramenta** chamando o `ingest_graph`.
5. Os itens "Comum aos dois" da seção 6 (trilha reconstruível, nenhum texto cru fora do processo incluindo checkpoints, gold set, tipo de minuta como dado).

**Específico de C1 (LangGraph + LangSmith + Django Admin)**
- `inspectdb` sobre o esquema: o que vira `TextField` ("guess") para `vector`/`tsvector`; usar `VectorField` ou excluir; tamanho real do código de `ModelAdmin`.
- Permissões por grupo (editor de matriz × só leitura) sem código por campo; medir o que falta.
- simple-history: capturar edições feitas no admin, mostrar `diff_against`, e o que **não** captura (SQL cru, `bulk_*`).
- Ação de admin "reindexar" em Python; Studio/Prompt Hub/anonimizador/custo por traço como na seção 6.

**Específico de C2 (LangGraph + Langfuse + Directus)**
- Introspecção do Directus sobre `vector`, `text[]`, `tsvector`, `jsonb` (ignora? quebra? lê?); tabelas `directus_*` criadas no mesmo banco.
- Revisões com *delta* presentes; tentativa de purga por admin; papel sem acesso a `directus_revisions`.
- Flow com webhook (ação não bloqueante) que dispara a reindexação; limite de coleções/Flows do plano Cloud; confirmar elegibilidade à MSCL.
- Langfuse: prompt editado na UI, experimento via UI sobre o gold set, fila de anotação com revisor; unidades por análise; esforço de operar PostgreSQL + ClickHouse + Redis + S3.

**Critérios de saída:** os da seção 6 (trilha reconstruível, não-dev edita sem ajuda, gold set comparando versões, horas de reescrita, custo mensal) mais: (f) **versão da matriz recuperável por análise após edição e após escrita por fora da ferramenta**; (g) horas para entregar a tela de gestão.

### 9.8 Lacunas e perguntas abertas deste adendo

1. Comportamento de Directus, NocoDB, Appsmith, ToolJet e Budibase com `vector`/`tsvector`/`text[]`: **não documentado**; só o protótipo resolve.
2. simple-history: editar/apagar linhas de histórico no admin (a configuração `SIMPLE_HISTORY_EDIT` do changelog 1.7.0 não foi reconfirmada) e uso com modelos `inspectdb`: **não encontrado**.
3. Directus: limite de plano para Content Versioning e revisões (**não informado**); página de preços inconsistente (Team US$ 588 × US$ 499).
4. NocoDB: divergência entre a página de papéis e a de preços sobre Teams no self-host; retenção do histórico por plano lida pela ordem das colunas (inferência).
5. Dify: lista de armazéns vetoriais veio de resumo parcial; RAGFlow: documentação oficial não renderizou, recuperação/edição de chunks e preço da nuvem não verificados.
6. Argilla: estado de manutenção não verificado; Label Studio: Postgres/requisitos e mapeamento por edição de logs/revisão não confirmados.
7. Context7 não foi usado nesta rodada (perguntas de licença, preço e hospedagem, só nas páginas oficiais); a rodada anterior usou Context7 para Directus e Langfuse.
8. Pergunta ao humano: a organização se enquadra na MSCL do Directus (receita < US$ 5 mi e < 50 pessoas)? Se não, C2 perde força e a combinação 3 sobe.
