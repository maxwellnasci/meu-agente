# RAG MVP — Especialista de Procedimentos (Supermercado Bom Preço)

Status: **Missão 2 concluída** (decisões, corpus, gabarito, blindagem de
testes). Ainda **sem código de RAG**. MVP local. Nada vai para a Contabo agora.

## Objetivo

Adicionar ao orquestrador LangGraph um especialista novo, `specialist_rag`,
que o supervisor aciona para perguntas sobre procedimentos internos. Ele
recupera trechos de um manual e devolve a resposta **com a fonte**
(arquivo + seção). Quando o manual não cobre o assunto, responde **"não sei"**.

O corpus é fictício: o manual de procedimentos do "Supermercado Bom Preço",
uma empresa inventada. A qualidade da busca é medida com um gabarito fixo antes
de qualquer ajuste (recall@5, ver *Resultados*).

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
| `orchestrator/fixtures/rag/gabarito.yaml` | 20 perguntas: 14 diretas, 3 que juntam duas seções, 3 sem resposta |
| `orchestrator/tests/test_rag_fixtures.py` | Garante que o gabarito aponta para arquivos e seções reais, com a distribuição combinada |
| `orchestrator/tests/conftest.py` | Blindagem: OpenRouter e `ORCHESTRATOR_RAG_*` neutralizados, `.env` ignorado, LLM real bloqueado |
| `orchestrator/tests/test_conftest_hermetico.py` | Prova a blindagem |

Armadilhas incluídas de propósito no corpus:

- **Assuntos parecidos em arquivos diferentes:**
  - −12 °C de aceite na doca (POP-01) × −18 °C de armazenamento (POP-05);
  - troca de perecível em 24 h × não perecível em 7 ou 30 dias (POP-03);
  - produto vencido na gôndola (POP-02) × vencido já vendido (POP-03);
  - etiqueta amarela (POP-07) × tabela de rebaixa (POP-02).
- **Códigos que só a busca por palavra-chave acha bem:** POP-06/POP-07,
  F-01, F-02, F-03, F-07, F-09, F-12, F-15, F-18, Q-14, Q-22, P-05, P-06.
- **Tabelas:** temperatura de aceite, rebaixa por validade, diluição,
  diferença de caixa e cores de etiqueta.
- **Sem resposta, mas quase:** multa de fornecedor (o POP-01 fala de horário,
  não de multa) e demissão por diferença de caixa (o POP-04 só prevê
  reciclagem).

## Blindagem dos testes

O `orchestrator/tests/conftest.py` tem três camadas, todas ativas antes de
qualquer `import orchestrator...`:

1. **Ambiente:** `ORCHESTRATOR_OPENROUTER_API_KEY` e as credenciais do n8n
   recebem valores falsos. Toda `ORCHESTRATOR_RAG_*` herdada do shell é
   removida.
2. **`.env` ignorado:** o `settings` global é reconstruído com
   `Settings(_env_file=None)`, e um teste de identidade prova que todos os
   módulos de produção (`main`, `nodes`, guards, clients, checkpointer)
   enxergam essa mesma instância. O que foi verificado:
   `test_conftest_hermetico.py` rodou com o `.env` real presente no cwd, e nem
   a chave do OpenRouter nem o token do gateway chegaram ao `settings`. A suíte
   **inteira** não foi rodada no checkout principal.
3. **LLM real bloqueado e reprovado:** a fixture autouse `blocked_llm_calls`
   troca `_generate/_agenerate/_stream/_astream` do `ChatOpenAI` por um erro
   `RealLLMCallBlocked`, sem rede e sem custo. Ela também **registra** cada
   tentativa e reprova o teste no teardown. Isso é necessário porque o
   `supervisor_node` engole exceções do LLM (`except Exception` → fallback
   openclaw): sem o registro, um teste sem mock passaria em silêncio. Isso foi
   provado com um teste descartável que chamava o supervisor sem mock:
   `1 passed, 1 error`, com a execução saindo em falha. Um teste que quer
   provocar o bloqueio de propósito pede a fixture pelo nome e chama
   `.clear()`.

Opt-in live do n8n (`RUN_LIVE_N8N_TESTS=1`): só as duas credenciais do n8n são
lidas, do ambiente ou do `.env`. OpenRouter e RAG continuam neutralizados.

Diagnóstico feito antes da blindagem: com um plugin espião no `ChatOpenAI`,
**nenhum** dos 359 testes chegava a uma chamada real ao LLM. A blindagem é
preventiva, para os testes de RAG que virão.

**Cuidado para a Missão 3:** o `Settings` usa `extra="forbid"`. Uma chave
`ORCHESTRATOR_RAG_*` posta no `.env` **antes** de existir o campo
correspondente em `config.py` derruba o import (`extra_forbidden`), ou seja,
derruba o orquestrador. Como variável de ambiente, ela é ignorada. Ordem
segura: primeiro o campo em `config.py` e nos dois `.env.example`, depois o
valor no `.env`.

## Baseline

| Momento | Testes |
|---|---|
| Antes da Missão 2 (`feat/rag-mvp` @ `33db106`) | **359 passed, 1 skipped** (o skip é o teste live do n8n) |
| Depois da Missão 2 | **383 passed, 1 skipped** (+16 blindagem, +8 consistência das fixtures) |

Comando: `cd orchestrator && python -m pytest -q`. A suíte precisa do repo
inteiro: `test_provision_client.py` usa `scripts/` da raiz.

## Método de avaliação

- **recall@5:** fração das perguntas `direta` e `multi_secao` (17) em que
  **todas** as seções de `secao_fonte` aparecem entre os 5 primeiros trechos
  recuperados. Numa `multi_secao`, achar só uma das duas seções conta como
  erro.
- **Sem resposta (3):** não entram no recall. Avaliam se a resposta final diz
  "não sei" em vez de inventar.
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
- Rodar a suíte inteira no checkout principal: verificado que os `TestClient`
  de `test_auth.py`/`test_turn_limits.py` são criados sem `with` (o lifespan
  não roda, então o `./data/checkpoints.sqlite` não é aberto). Mesmo assim, o
  hábito seguro continua sendo rodar num worktree limpo.
