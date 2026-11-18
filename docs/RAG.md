# RAG MVP — Especialista de Procedimentos (Supermercado Bom Preço)

Status: **Missão 2 concluída e revisada** (decisões, corpus, gabarito,
blindagem de testes; correções da revisão adversária do `ff259cb` aplicadas).
Ainda **não existe código de RAG**: nenhum `specialist_rag`, nenhuma ingestão,
nenhum índice, nenhum script de avaliação. Tudo abaixo que fala do especialista
é **plano**. MVP local. Nada vai para a Contabo agora.

## Objetivo

Adicionar (ainda não feito) ao orquestrador LangGraph um especialista novo,
`specialist_rag`, que o supervisor acionará para perguntas sobre procedimentos internos. Ele
recupera trechos de um manual e devolve a resposta **com a fonte**
(arquivo + seção). Quando o manual não cobre o assunto, responde **"não sei"**.

O corpus é fictício: o manual de procedimentos do "Supermercado Bom Preço",
uma empresa inventada. A qualidade da busca **será** medida com um gabarito
fixo antes de qualquer ajuste (recall@5, ver *Resultados*, ainda vazio).

Encaixe previsto (Missão 1): um nó só de leitura, que roda dentro do
orquestrador. Ele grava trechos e fontes no `internal_scratchpad` (`[rag] ...`)
e o `synthesize_final` compõe a resposta. Não há gate de confirmação, porque o
nó não executa ação. A ingestão é um script offline fora do grafo.

## Decisões

| Decisão | Por quê |
|---|---|
| **Embeddings locais com `fastembed`** (modelo multilíngue, CPU, sem API) | Corpus e perguntas em português. Rodar em CPU não exige GPU nem serviço novo. Sem API externa: custo zero por consulta, nada do manual sai da máquina e os testes não dependem de rede. `fastembed` usa ONNX, sem PyTorch, então a imagem fica bem menor. O modelo exato será escolhido na Missão 3, entre os multilíngues que o `fastembed` suporta. |
| **`sqlite-vec` (vetorial) + FTS5 (palavra-chave/BM25)**, busca híbrida com **RRF** | O projeto já é SQLite: sem servidor novo, sem porta, backup = copiar arquivo. Só vetorial erra códigos exatos ("POP-07", "F-12", "Q-22"); só BM25 erra paráfrases de WhatsApp ("900 conto na gaveta" → sangria). O RRF (Reciprocal Rank Fusion) junta os dois rankings pela **posição**, sem calibrar escalas de score diferentes. |
| **Arquivo separado do `checkpoints.sqlite`** | Ciclos de vida diferentes. O índice é **derivado** do corpus: pode ser apagado e reconstruído pela ingestão a qualquer momento. O checkpoint é **estado de conversa** e não pode ser perdido. Separados, um rebuild do índice nunca encosta no histórico, e não há disputa de lock de escrita entre ingestão e grafo. Os dois ficam no volume `data/`. |
| **Um índice só, com campo `colecao`** | MVP simples: um arquivo, uma ingestão. O campo `colecao` (hoje `supermercado`) filtra a busca e deixa o caminho aberto para multi-cliente sem migrar esquema. |
| **MVP local, nada de Contabo** | Primeiro medir a qualidade com o gabarito. Deploy só depois de recall aceitável e de revisar o `SECURITY.md` (LLM08). |

## Artefatos desta missão

| Caminho | O quê |
|---|---|
| `orchestrator/fixtures/rag/supermercado/` | 6 POPs em Markdown (POP-01 a POP-05 e POP-07). O POP-06 aparece citado como "revogado", de propósito. |
| `orchestrator/fixtures/rag/gabarito.yaml` | 20 perguntas: 14 diretas, 3 que juntam duas seções, 3 sem resposta, com critério de acerto |
| `orchestrator/tests/test_rag_fixtures.py` | Consistência do gabarito com o corpus (ver abaixo). Não testa RAG nenhum. |
| `orchestrator/tests/conftest.py` | Blindagem da suíte (ver *Blindagem dos testes*) |
| `orchestrator/tests/hermetic_support.py` | Constantes/tipos da blindagem, sem efeitos colaterais (os testes importam daqui, nunca do conftest) |
| `orchestrator/tests/_probe_hermetic.py` | Sonda rodada num pytest filho; a suíte normal não a coleta |
| `orchestrator/tests/test_conftest_hermetico.py` | Prova a blindagem, um teste por achado da revisão |

O que o `test_rag_fixtures.py` garante (e só isso):

- arquivos e seções citados no gabarito existem (título exato do cabeçalho);
- distribuição 14/3/3 e quantidade de fontes por tipo;
- nenhuma pergunta copia o manual: janela de 6 palavras comparada **sem
  acento, sem pontuação e sem caixa**; pergunta com menos de 6 palavras é
  comparada inteira;
- todo código citado no gabarito (`POP-xx`, `F-xx`, `Q-xx`, `P-xx`, em
  pergunta, resposta, armadilha e critérios) existe no corpus, e os citados
  na resposta de uma pergunta com fonte estão nas seções-fonte (ou são o
  código do próprio POP-fonte);
- cada `multi_secao` tem, por seção, um `trecho_exclusivo` que só aquela
  seção contém e que a resposta esperada exige;
- cada `sem_resposta` declara `criterio_acerto`; q19 e q20 têm `aceita_tambem`
  citando a regra relacionada.

Armadilhas incluídas de propósito no corpus:

- **Assuntos parecidos em arquivos diferentes:**
  - −12 °C de aceite na doca (POP-01) × −18 °C de armazenamento (POP-05);
  - troca de perecível em 24 h × não perecível em 7 ou 30 dias (POP-03);
  - produto vencido na gôndola (POP-02) × vencido já vendido (POP-03). A
    diferença é **intencional**: na gôndola, antes de pagar, o operador ou
    fiscal troca na hora (POP-02); depois de pagar, a troca é no balcão de
    Atendimento (POP-03);
  - etiqueta amarela (POP-07) × tabela de rebaixa (POP-02).
- **O F-07 tem dois usos no POP-01:** divergência de nota (seção 3) e registro
  de temperatura de toda entrega (seção 4), além de validade e avaria
  (seções 5 e 6). Por isso a q07 cita o F-07 **e** uma divergência de preço
  na nota: a busca por código acha as quatro seções, e só a seção 3 responde.
- **Códigos que só a busca por palavra-chave acha bem:** POP-06/POP-07,
  F-01, F-02, F-03, F-07, F-09, F-12, F-15, F-18, Q-14, Q-22, Q-23, P-05, P-06.
- **Tabelas:** temperatura de aceite, rebaixa por validade, diluição,
  diferença de caixa e cores de etiqueta.
- **Sem resposta, mas quase:** multa de fornecedor (o POP-01 fala de horário,
  não de multa) e demissão por diferença de caixa (o POP-04 só prevê
  reciclagem).

Correção de conteúdo feita na revisão: o POP-02 dizia que toda sobra de
padaria do dia ia para doação, mas a coleta só acontece terça e sexta. Agora
a sobra de padaria só é doada no dia da coleta. Nos outros dias, vira quebra
`Q-23 (Sobra de produção)`.

## Blindagem dos testes

Tudo no `orchestrator/tests/conftest.py` roda no **nível de módulo**: antes de
qualquer `import orchestrator...`, antes da coleta e antes de qualquer
fixture. Se o pacote `orchestrator` já estiver importado quando o conftest
roda, ele aborta.

1. **Ambiente.** Toda `ORCHESTRATOR_*` herdada do shell é removida. As
   variáveis lidas direto pelos SDKs também são removidas: `LANGCHAIN_API_KEY`,
   `LANGSMITH_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `HF_TOKEN` e afins
   (lista em `hermetic_support.py`). `LANGCHAIN_TRACING_V2`/`LANGSMITH_TRACING`
   ficam em `"false"`. Depois entram só valores falsos: chave do OpenRouter,
   n8n em `https://n8n.test.invalid` e gateway do OpenClaw em
   `http://openclaw-gateway.test.invalid:18789`, **sem token**.
2. **Rede bloqueada no socket** (`pytest-socket`, dependência de dev). O
   `disable_socket(allow_unix_socket=True)` bloqueia `socket.socket` e o DNS
   (`getaddrinfo`) no processo inteiro: coleta, fixtures de sessão/módulo e
   todos os testes. O AF_UNIX fica liberado porque o event loop do asyncio
   usa. O **plugin** do pytest-socket fica desligado (`-p no:socket` no
   `addopts`), porque o teardown dele religa a rede depois de cada teste. O
   plugin do LangSmith também fica desligado (`-p no:langsmith_plugin`),
   porque importa o SDK antes do conftest.
   - Consequência: o caminho "LLM falha → supervisor cai no fallback →
     especialista faz POST ao gateway" agora estoura em `SocketBlockedError`
     já no primeiro POST (provado em
     `test_fallback_do_supervisor_nao_faz_post_ao_gateway`). A revisão
     adversária observou até 12 POSTs ao gateway nesse caminho antes do
     bloqueio. Na suíte atual, só os testes de blindagem tentam abrir socket.
   - Guarda de ambiente: depois de cada teste, a fixture autouse
     `hermetic_env_guard` compara as `ORCHESTRATOR_*` e as variáveis de SDK
     com o estado hermético. Se mudaram, restaura e reprova o teste. Foi assim
     que apareceu o `test_langsmith_tracing_config.py` apagando o
     `LANGCHAIN_TRACING_V2="false"` para o resto da suíte (corrigido com
     `patch.dict(os.environ)`).
   - Exceção estreita: `hermetic_support.loopback_socket()`, usado só pelo
     `test_provision_client.py` para reservar porta. Só faz `bind` em
     127.0.0.1 e recusa `connect`/envio.
3. **`.env` nunca é lido, nem no import.** `orchestrator.config` faz
   `settings = Settings()` no import, e o pydantic-settings lê `.env` relativo
   ao cwd. O conftest importa o módulo com o cwd num diretório temporário
   vazio e depois ainda reconstrói o `settings` com `_env_file=None`. A prova
   roda um pytest filho com um `.env` canário (porta inválida) no cwd e um
   audit hook de `open()`: nenhum `.env` é aberto e a suíte sobe.
4. **LLM real bloqueado e reprovado.** `_generate/_agenerate/_stream/_astream`
   do `ChatOpenAI` são trocados no nível de módulo por `RealLLMCallBlocked`,
   então o bloqueio vale também na coleta e em fixtures de sessão/módulo. Toda
   tentativa é registrada:
   - dentro de um teste, a fixture autouse `blocked_llm_calls` reprova o
     teste no teardown. Isso é necessário porque o `supervisor_node` engole
     exceções do LLM;
   - fora de um teste, `pytest_sessionfinish` reprova a sessão.

   Um teste que provoca o bloqueio de propósito pede `blocked_llm_calls` (ou
   `llm_calls_outside_tests`) pelo nome e chama `.clear()`.

**Opt-in live do n8n** (`RUN_LIVE_N8N_TESTS=1`): as duas credenciais do n8n
do shell são retiradas do `os.environ` e guardadas numa variável privada do
conftest. O `settings` global continua com o n8n falso. Só a fixture
`live_n8n_credentials` aplica as credenciais (do shell ou, se faltarem, de
`orchestrator/.env`) e religa a rede, e só durante o teste que a usa. A
fixture recusa qualquer teste além de
`test_specialist_n8n.py::test_create_and_delete_workflow_against_real_n8n_instance`
(e da sonda) e pula sem o opt-in. OpenRouter, gateway e RAG continuam
neutralizados nesse modo.

**Cuidado para a Missão 3:** o `Settings` herda o `extra="forbid"` padrão do
pydantic-settings. Uma chave `ORCHESTRATOR_RAG_*` posta no `.env` **antes** de
existir o campo correspondente em `config.py` derruba o import
(`extra_forbidden`), ou seja, derruba o orquestrador (verificado). Como
variável de ambiente, ela é ignorada (verificado). Ordem segura: primeiro o
campo em `config.py` e nos dois `.env.example`, depois o valor no `.env`.

## Baseline

| Momento | Testes |
|---|---|
| Antes da Missão 2 (`feat/rag-mvp` @ `33db106`) | **359 passed, 1 skipped** (o skip é o teste live do n8n) |
| Missão 2 (`ff259cb`) | 383 passed, 1 skipped |
| Depois da revisão adversária | **412 passed, 1 skipped** (33 blindagem, 20 consistência das fixtures) |

Comando: `cd orchestrator && python -m pytest -q`. A suíte precisa do repo
inteiro: `test_provision_client.py` usa `scripts/` da raiz. Com a rede
bloqueada, ela foi rodada no checkout principal (com `.env` real presente),
com e sem `RUN_LIVE_N8N_TESTS=1`. No modo live, o único teste live ficou
desmarcado (`--deselect`), para não escrever no n8n de produção.

## Método de avaliação

Ainda **não há script de avaliação**. O método abaixo é o que a Missão 3 vai
implementar.

- **recall@5:** fração das perguntas `direta` e `multi_secao` (17) em que
  **todas** as seções de `secao_fonte` aparecem entre os 5 primeiros trechos
  recuperados. Numa `multi_secao`, achar só uma das duas seções conta como
  erro. O `trecho_exclusivo` garante que isso também vale para a resposta:
  com uma seção só, falta uma parte indispensável.
- **Sem resposta (3):** não entram no recall. Cada uma é julgada pelo seu
  `criterio_acerto`. Regra geral: é **acerto** dizer "não sei" **ou** dizer
  que o manual não prevê aquilo citando a regra relacionada (q19: horário e
  40 min de doca do POP-01; q20: reciclagem de 4 h do POP-04), **desde que a
  resposta não invente valor, prazo ou número**. Inventar uma multa, um
  percentual ou um limite de diferenças para demissão é erro. A q18 (férias)
  não tem regra relacionada: só "não sei" ou "o manual não trata disso".
- Medir separadamente: só vetorial, só BM25 e híbrido (RRF). É assim que se
  vê se a busca híbrida se paga.

## Resultados

*(vazio: recall@5 a medir na próxima missão)*

| Configuração | recall@5 (17) | Diretas (14) | Multi-seção (3) | "Não sei" correto (3) |
|---|---|---|---|---|
| Só vetorial | | | | |
| Só BM25 (FTS5) | | | | |
| Híbrido (RRF) | | | | |

## Pendências

- Atualizar a linha **LLM08** do `SECURITY.md` (hoje "não aplicável") e
  revisar LLM01 e LLM04: os trechos recuperados são entrada indireta no prompt.
- Escolher o modelo multilíngue do `fastembed` e a estratégia de chunking
  (por seção `##` é o candidato natural, já que o gabarito é por seção).
  **Atenção:** a resposta da q13 (POP-06 revogado) está no preâmbulo do POP-07,
  entre o título `#` e a primeira seção `##`. Um chunker que só corta em `##`
  precisa emitir esse preâmbulo como chunk próprio, ligado ao título `#`. Sem
  isso, a q13 fica irrespondível por construção.
- Escrever o script de avaliação (recall@5 e critério das `sem_resposta`):
  hoje só existe o gabarito.
- O bloqueio de socket não cobre processos filhos (`subprocess`): um teste
  que chame um binário que acesse a rede não é pego. Hoje rodam subprocesso
  o `test_provision_client.py` (o script de provisionamento, sem rede) e o
  `test_conftest_hermetico.py` (um pytest filho, que carrega o mesmo
  conftest e portanto também fica bloqueado).
