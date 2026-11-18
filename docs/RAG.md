# RAG MVP — Especialista de Procedimentos (Supermercado Bom Preço)

Status: **Missão 3 concluída** (motor de busca + primeira medição de
recall@5), ainda **sem commit** e sem revisão adversária. Existe o módulo
`orchestrator/src/orchestrator/rag/`: chunking, ingestão offline, índice
SQLite próprio (sqlite-vec + FTS5), busca nos 3 modos e o script de avaliação.
**Ainda não existe `specialist_rag`**: nada disso está ligado ao grafo nem ao
supervisor (Missão 4). Tudo abaixo que fala do especialista é **plano**. MVP
local. Nada vai para a Contabo agora.

## Objetivo

Adicionar (ainda não feito) ao orquestrador LangGraph um especialista novo,
`specialist_rag`, que o supervisor acionará para perguntas sobre procedimentos internos. Ele
recupera trechos de um manual e devolve a resposta **com a fonte**
(arquivo + seção). Quando o manual não cobre o assunto, responde **"não sei"**.

O corpus é fictício: o manual de procedimentos do "Supermercado Bom Preço",
uma empresa inventada. A qualidade da busca **será** medida com um gabarito
fixo antes de qualquer ajuste. A primeira medição (recall@5) está em *Resultados*.

Encaixe previsto (Missão 1): um nó só de leitura, que roda dentro do
orquestrador. Ele grava trechos e fontes no `internal_scratchpad` (`[rag] ...`)
e o `synthesize_final` compõe a resposta. Não há gate de confirmação, porque o
nó não executa ação. A ingestão é um script offline fora do grafo.

## Decisões

| Decisão | Por quê |
|---|---|
| **Embeddings locais com `fastembed`** (modelo multilíngue, CPU, sem API) | Corpus e perguntas em português. Rodar em CPU não exige GPU nem serviço novo. Sem API externa: custo zero por consulta, nada do manual sai da máquina e os testes não dependem de rede. `fastembed` usa ONNX, sem PyTorch, então a imagem fica bem menor. |
| **Modelo: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** (384 dim, 0,22 GB) | Missão 3. É o menor dos 4 multilíngues que o `fastembed` 0.9.1 suporta. Os outros: `paraphrase-multilingual-mpnet-base-v2` (768 dim, 1 GB), `multilingual-e5-large` (1024 dim, 2,24 GB) e `potion-multilingual-128M` (256 dim). Foi escolhido como ponto de partida da medição, não por ter ganho uma comparação. **Limite conhecido:** o tokenizer dele trunca em **128 tokens**, e 15 dos 46 chunks passam disso (o maior tem 275). Ver *Resultados*. O embedder usa `query_embed`/`passage_embed`, então trocar para o e5 (que exige os prefixos `query:`/`passage:`) não pede mudança de código, só reingestão. |
| **Chunk = seção `##`; preâmbulo vira chunk próprio** | O gabarito é por seção. O preâmbulo (entre o `#` e a primeira `##`) vira um chunk cuja `seção` é o texto do título `#`: é onde está a q13. Subseções `###` ficam dentro da `##` delas. O texto indexado (embedding e FTS5) leva o título do documento na frente (`POP-04 — Abertura e Fechamento de Caixa` + `## 2. Sangria`…). O `texto` devolvido como fonte é só o da seção. |
| **Query BM25 sanitizada** | A pergunta nunca chega crua ao `MATCH` do FTS5. Códigos (`POP-06`, `F-12`…) viram **frase** (`"pop 06"`), para não virar `pop OR 06`. O resto vira palavras entre aspas unidas por `OR`. Tokenizer `unicode61 remove_diacritics 2`, porque as perguntas chegam sem acento. Sem stopwords e sem stemming (baseline, ver *Resultados*). |
| **RRF com k = 60 e 50 candidatos por ranking** | Valor padrão da literatura, sem calibrar. O empate é decidido pela melhor posição individual, depois pelo menor id (determinístico). |
| **`sqlite-vec` (vetorial) + FTS5 (palavra-chave/BM25)**, busca híbrida com **RRF** | O projeto já é SQLite: sem servidor novo, sem porta, backup = copiar arquivo. Só vetorial erra códigos exatos ("POP-07", "F-12", "Q-22"); só BM25 erra paráfrases de WhatsApp ("900 conto na gaveta" → sangria). O RRF (Reciprocal Rank Fusion) junta os dois rankings pela **posição**, sem calibrar escalas de score diferentes. |
| **Arquivo separado do `checkpoints.sqlite`** (`data/rag_index.sqlite`) | Ciclos de vida diferentes. O índice é **derivado** do corpus: pode ser apagado e reconstruído pela ingestão a qualquer momento. O checkpoint é **estado de conversa** e não pode ser perdido. Separados, um rebuild do índice nunca encosta no histórico, e não há disputa de lock de escrita entre ingestão e grafo. Os dois ficam no volume `data/`. A ingestão monta o índice num arquivo temporário e só troca no fim (`os.replace`): uma ingestão que falhe nunca deixa índice pela metade. Ela recusa `--db …/checkpoints.sqlite`. A tabela `meta` guarda modelo e dimensão, e a busca recusa um embedder diferente (`IndexMismatchError`). |
| **Um índice só, com campo `colecao`** | MVP simples: um arquivo, uma ingestão. O campo `colecao` (hoje `supermercado`) filtra a busca e deixa o caminho aberto para multi-cliente sem migrar esquema. |
| **MVP local, nada de Contabo** | Primeiro medir a qualidade com o gabarito. Deploy só depois de recall aceitável e de revisar o `SECURITY.md` (LLM08). |

## Artefatos da Missão 2

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

## Artefatos da Missão 3

| Caminho | O quê |
|---|---|
| `orchestrator/src/orchestrator/rag/chunking.py` | `Chunk(arquivo, secao, texto, colecao)`: um chunk por `##`, mais o preâmbulo |
| `orchestrator/src/orchestrator/rag/embeddings.py` | Protocolo `Embedder` e `FastEmbedEmbedder` (import preguiçoso: importar `orchestrator.rag` não carrega fastembed nem onnxruntime) |
| `orchestrator/src/orchestrator/rag/store.py` | Índice: `meta`, `chunks`, `chunks_fts` (FTS5), `chunks_vec` (`vec0`, cosseno, `colecao` como metadado). Rebuild atômico; leitura em `mode=ro` |
| `orchestrator/src/orchestrator/rag/search.py` | `search(conn, pergunta, modo="vetorial" \| "bm25" \| "hibrido", k=5, colecao=...)`, `fts_query`, `rrf_fuse` |
| `orchestrator/src/orchestrator/rag/ingest.py` | `python -m orchestrator.rag.ingest` (script offline) |
| `orchestrator/src/orchestrator/rag/evaluate.py` | `python -m orchestrator.rag.evaluate [--json saida.json]` |
| `orchestrator/tests/test_rag_engine.py` | 42 testes com embedder **falso** (hash de palavras). Inclui o contrato "cada fonte do gabarito é exatamente 1 chunk" |
| `orchestrator/pyproject.toml` | Extra novo `rag` (`fastembed`, `sqlite-vec`); `sqlite-vec` também no `dev`, porque os testes usam o índice de verdade |

Como rodar (fora do pytest; o primeiro `ingest` baixa o modelo para
`orchestrator/data/fastembed_cache/`):

```bash
cd orchestrator
pip install -e ".[rag]"
python -m orchestrator.rag.ingest      # -> data/rag_index.sqlite (46 chunks)
python -m orchestrator.rag.evaluate    # tabela de recall@5 + falhas por pergunta
```

Os scripts não leem `orchestrator.config` nem `.env`. Caminhos, modelo e
coleção vêm por argumento (`--db`, `--corpus`, `--model`, `--colecao`,
`--cache-dir`), com defaults em `orchestrator/data/` e
`orchestrator/fixtures/rag/`. Por isso nenhum campo `ORCHESTRATOR_RAG_*` foi
criado em `config.py` (o aviso do `extra="forbid"` abaixo continua valendo
para a Missão 4).

**Python 3.14 (venv local):** `fastembed` 0.9.1, `onnxruntime` 1.32.0 (wheel
`cp314` nativa) e `sqlite-vec` 0.1.9 instalam com `--only-binary=:all:` e
rodam: a extensão carrega, o KNN funciona e o embedding real foi gerado. O CI
roda **Python 3.11** com `.[dev]`. Lá o `sqlite_vec.load()` depende de o
`sqlite3` do Python do runner permitir `enable_load_extension`. Isso **não foi
verificado** (não houve push).

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
     127.0.0.1 e recusa `connect`/envio. Ele herda do `socket.socket` da
     stdlib, guardado em `hermetic_support.STDLIB_SOCKET` no import (antes do
     `disable_socket()`; o conftest confere logo depois). Não usa mais a API
     privada `pytest_socket._true_socket`.
   - Se alguém tirar o `-p no:socket` ou o `-p no:langsmith_plugin` do
     `addopts`, o `pytest_configure` do conftest derruba a sessão. Isso é
     provado num pytest filho com cada plugin religado.
3. **`.env` nunca é lido, nem no import.** `orchestrator.config` faz
   `settings = Settings()` no import, e o pydantic-settings lê `.env` relativo
   ao cwd. O conftest importa o módulo com o cwd num diretório temporário
   vazio e depois ainda reconstrói o `settings` com `_env_file=None`. A prova
   roda um pytest filho com um `.env` canário (porta inválida) no cwd e um
   audit hook de `open()`: nenhum `.env` é aberto e a suíte sobe.
4. **Embedder real do RAG bloqueado.** O conftest marca `fastembed` e
   `onnxruntime` como `None` em `sys.modules`, então `import fastembed` vira
   `ImportError` na suíte. Sem isso, como o modelo fica em cache em
   `data/fastembed_cache/`, um teste que usasse o embedder real por engano
   rodaria **offline** e passaria escondido.
5. **LLM real bloqueado e reprovado.** `_generate/_agenerate/_stream/_astream`
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
(e da sonda) e pula sem o opt-in. A sonda prova os dois lados: **durante** a
fixture, rede liberada e credenciais canário; **depois** dela, no teste
seguinte, `SocketBlockedError` e o n8n falso de volta (no `settings` e no
ambiente). OpenRouter, gateway e RAG continuam
neutralizados nesse modo.

**Cuidado para a Missão 4** (a Missão 3 não criou campo nenhum): o `Settings` herda o `extra="forbid"` padrão do
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
| Depois da revisão adversária (`7aaa5a7`) | 412 passed, 1 skipped (33 blindagem, 20 consistência das fixtures) |
| Missão 3 (sem commit) | **455 passed, 1 skipped, 1 xfailed** (+42 motor do RAG, +1 fixtures, +1 blindagem líquido) |

Comando: `cd orchestrator && python -m pytest -q`. A suíte precisa do repo
inteiro: `test_provision_client.py` usa `scripts/` da raiz. Com a rede
bloqueada, ela foi rodada no checkout principal (com `.env` real presente),
com e sem `RUN_LIVE_N8N_TESTS=1`. No modo live, o único teste live ficou
desmarcado (`--deselect`), para não escrever no n8n de produção.

## Método de avaliação

Implementado em `orchestrator.rag.evaluate` (só o recall; o julgamento das
`sem_resposta` depende da resposta gerada, Missão 4).

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

Primeira medição, **antes de qualquer ajuste** (2026-11-18). Modelo
`paraphrase-multilingual-MiniLM-L12-v2`, 46 chunks (6 POPs), k = 5, RRF k = 60.
Reingestão e reavaliação deram resultado idêntico (determinístico).

| Configuração | recall@5 (17) | Diretas (14) | Multi-seção (3) | "Não sei" correto (3) |
|---|---|---|---|---|
| Só vetorial | **13/17 (76%)** | 11/14 | 2/3 | não medido (Missão 4) |
| Só BM25 (FTS5) | **14/17 (82%)** | 11/14 | 3/3 | não medido (Missão 4) |
| Híbrido (RRF) | **14/17 (82%)** | 12/14 | 2/3 | não medido (Missão 4) |

Falhas por pergunta. O número é a posição em que a fonte que faltou apareceu,
até a 50ª; "—" significa que não apareceu.

| Pergunta | Vetorial | BM25 | Híbrido | Fonte que faltou |
|---|---|---|---|---|
| q04 (queijo, troca) | ok | — | 23 | POP-03 §3 Prazo de troca — perecíveis |
| q05 (troca não perecível) | ok | 9 | ok | POP-03 §4 Prazo de troca — não perecíveis |
| q10 (diferença de caixa) | 9 | 8 | 7 | POP-04 §6 Diferença de caixa |
| q11 (diluição) | 15 | ok | ok | POP-05 §2 Diluição dos produtos de limpeza |
| q14 (desconto iogurte) | 6 | ok | ok | POP-02 §3 Rebaixa de preço |
| q16 (etiqueta amarela × vermelha) | 14 | ok | 6 | POP-02 §3 Rebaixa de preço (a outra fonte, POP-07 §2, veio) |

Leitura (hipóteses, **não verificadas**: nada foi ajustado):

- **O híbrido empatou com o BM25 no total (14/17), mas não falhou nas mesmas
  perguntas.** Contra o BM25, ganhou a q05 e perdeu a q16. Contra o vetorial,
  ganhou a q11 e a q14 e perdeu a q04. A q10 falha nos três modos.
- **q04 mostra o custo do RRF.** O vetorial põe a seção no top 5, mas ela não
  casa nenhum termo no BM25 e fica fora daquele ranking. Só com a contribuição
  do vetorial, o RRF a empurra para a 23ª posição.
- **O truncamento em 128 tokens não explica as falhas do vetorial.** As 4
  falhas estão em chunks acima de 128 tokens: q10 (166), q11 (187), q14 e q16
  (218). Mas o trecho que responde cai **dentro** da janela: q10 "R$ 5,00" no
  token 48, q14 "30%" no 117, q16 "encarregado de perecíveis" no 32. Na q11,
  "10 ml" está no 74 e "15 minutos" no 138. Já a q02 e a q06 acertaram no
  vetorial com chunks truncados (275 e 175 tokens), e a resposta da q02
  ("−12") fica no token 142, fora da janela. Há correlação, mas não causa.
  Trocar de modelo continua candidato, por outro motivo: qualidade do
  embedding em PT informal.
- **BM25 sem stemming:** q04 ("trocar", "comprou anteontem") não casa com
  "troca"/"perecíveis" e a seção nem aparece no ranking. Sem stopwords, as
  palavras de ligação também competem. Num teste, "onde fica o F-18?" trouxe
  primeiro "1. Onde é feita a troca" (POP-03), por causa do "onde", em vez da
  seção do F-18 (ver *Achados*).
- **q10** ("fechei o caixa faltando 3 reais, vou ter problema?") é
  paráfrase pura de uma seção longa (166 tokens) com tabela, sem nenhuma
  palavra rara em comum com ela: ruim para os dois.

### Achados

- **Expectativa ajustada após ver o resultado foi revertida; falha mantida
  como xfail.** No `test_rag_engine.py`, o caso BM25 "onde fica o F-18?"
  falhou: o "onde" puxou "1. Onde é feita a troca" (POP-03) para o topo. A
  primeira reação foi trocar a pergunta por "F-18", mas isso é ajustar a
  expectativa ao resultado. A pergunta original voltou e ficou marcada como
  `xfail(strict=True, reason="BM25 sem stopwords em português: 'onde' puxa
  outra seção")`. Por ser `strict`, quando as stopwords forem implementadas o
  caso passa a acertar, vira XPASS e **reprova** a suíte. Esse é o sinal para
  tirar o `xfail`.
- O `gabarito.yaml` **não foi alterado** nesta missão (o último commit que o
  toca é o `7aaa5a7`, da Missão 2), nem os POPs em `fixtures/rag/supermercado/`.

## Pendências

- Atualizar a linha **LLM08** do `SECURITY.md` (hoje "não aplicável") e
  revisar LLM01 e LLM04: os trechos recuperados são entrada indireta no prompt.
- Missão 4: ligar ao grafo (`specialist_rag`) e julgar as 3 `sem_resposta`
  pelo `criterio_acerto` (exige a resposta gerada). Decidir se `fastembed` e
  `sqlite-vec` vão para as dependências principais (o `fastembed` traz o
  `onnxruntime` para a imagem) e onde o índice é gerado no deploy (o
  `Dockerfile` não copia `fixtures/`).
- Ajustes candidatos, **um por vez e medindo de novo**: modelo com janela
  maior (truncamento em 128 tokens), stopwords e stemming em PT no BM25, peso
  extra para códigos exatos. Cuidado: com 17 perguntas, ajustar até o número
  subir é sobreajuste ao gabarito.
- Verificar o `sqlite_vec.load()` no Python 3.11 do CI (primeiro push).
- O bloqueio de socket não cobre processos filhos (`subprocess`): um teste
  que chame um binário que acesse a rede não é pego. Hoje rodam subprocesso
  o `test_provision_client.py` (o script de provisionamento, sem rede), o
  `test_conftest_hermetico.py` (um pytest filho, que carrega o mesmo
  conftest e portanto também fica bloqueado) e o
  `test_rag_engine.py::test_importar_o_rag_nao_carrega_fastembed` (um
  `python -c` que só importa o pacote, num cwd vazio, **sem** o bloqueio).

## Processo

Implementação: Claude Code. Revisão adversária: Gemini 4 Argon (high), via
Antigravity. Decisões e validação: Max.
