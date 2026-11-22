# Pré-registro — Mini-teste q02 e q04 (`v1` × `v4`)

Data do pré-registro: 2026-11-21 (escrito **antes** de qualquer execução paga).

> **Emendado em 21/11/2026, antes de qualquer medição** (§9, após revisão adversária do Claude Code). O texto original foi mantido; o que foi substituído aparece ~~tachado~~ com a marca **[→ Emenda E-…]**. Limites conhecidos na §10.

## 1. Objetivo e escopo

Verificar no modelo de produção (`deepseek/deepseek-chat`) se a proposta de regras **`v4`** (`v1` + Regra 6, originada na exploração com subagentes em `docs/exploracao/subagentes-q02.md`) corrige os erros de conclusão em perguntas de Sim/Não com limite numérico ou prazo — especificamente a **q02** (temperatura negativa) e a **q04** (prazo relativo).

> **Isto é apenas um SINAL** para decidir se vale montar a Missão 11. Este mini-teste **não adota nada**: a `v4` só pode virar padrão de produção depois, pela Missão 11 completa (as 20 perguntas do gabarito + a prova lacrada, com pré-registro próprio).

## 2. Versões congeladas

- **`v1` (linha de base / produção atual):** `REGRAS_DO_MANUAL` em `orchestrator/src/orchestrator/graph/rag_specialist.py`, sem alteração.
  - `sha256` da string injetada no `synthesize_final`: `3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240` (idêntico às Missões 8, 9 e 10).
- **`v4` (proposta do Antigravity):** texto completo de `docs/exploracao/regras-proposta.txt`.
  - Invariante verificado por código: `v4 = "\n\n" + texto_arquivo.rstrip("\n")` começa **exatamente** (byte a byte) por `REGRAS_DO_MANUAL` (`v4.startswith(v1) == True`), com acréscimo iniciando em `\n6. Em perguntas de decisao...` (+1.692 caracteres).
  - `sha256` do arquivo bruto (`docs/exploracao/regras-proposta.txt`): `4c23e9c03e040c9972d438fb58aa43f9c18f6990d13b9f8bb99a0fa16497070b`.
  - `sha256` da string exata injetada no `synthesize_final`: `646921f245b120a1faeac60df499054dc238a1f863f537e91d59147a3600e1a0`.
- **Isolamento de produção:** o padrão `settings.rag_regras_versao = "v1"`, `REGRAS_POR_VERSAO` e `REGRAS_DA_ETAPA1_POR_VERSAO` **não** são alterados. A `v4` só existe por parâmetro dentro do script do mini-teste (`orchestrator/src/orchestrator/rag/mini_q02.py`), injetada apenas durante a chamada do `synthesize_final` e restaurada em bloco `finally`.

## 3. Desenho experimental

- **Perguntas:** somente `q02` e `q04` de `orchestrator/fixtures/rag/gabarito.yaml`:
  - `q02`: *"chegou frango congelado marcando -10 graus no termometro, aceito?"* (fonte: `POP-01`, seção `"4. Temperatura na chegada"`).
  - `q04`: *"cliente quer trocar um queijo que comprou anteontem, posso trocar?"* (fonte: `POP-03`, seção `"3. Prazo de troca — produtos perecíveis"`).
- **Pipeline:** grafo completo (`supervisor -> specialist_rag -> supervisor -> synthesize_final`), busca híbrida `top_k = 5`, sem rerank, índice SQLite da Missão 8 (`indice_meta` conferido), mesmos modelos e configuração da Missão 10 (`deepseek/deepseek-chat`, supervisor com temperatura `0`, synth sem temperatura fixa, sem etapa 2 / formatador).
- **Tamanho da amostra:** `N = 10` amostras por pergunta por versão → `2 × 2 × 10 = 40` respostas no total.
- **Ordem intercalada:** estritamente alternada `v1, v4, v1, v4…` pareada por pergunta em cada amostra (`(q02, v1), (q02, v4), (q04, v1), (q04, v4)` repetido para amostras `1..10`), para diluir deriva temporal do provedor.
- **Sem juiz pago:** nenhuma chamada de LLM juiz.
- **Registro bruto:** gravado em `orchestrator/fixtures/rag/explore/mini-q02/respostas.json`, contendo por resposta: `versao`, `regras_sha256`, `id`, `amostra`, `indice_execucao`, `pergunta`, rota (`caminho` e `rag_acionado`), `trechos` recebidos, `resposta_crua` (e `resposta_final`), `falha_de_infra` / `erro` / `erros_llm`, `custo_usd` e tempos (`tempo_synth_s` e `tempo_total_s`). O log da execução não imprime o texto das respostas, preservando a cegueira até a classificação.

## 4. Classificação cega (grátis)

Depois da coleta, `--classificar-arquivo` embaralha as 40 respostas ~~com semente fixa e gravada (padrão `20261121`)~~ **[→ Emenda E-M01: semente sorteada com `secrets`, gravada só no mapa]** e grava dois arquivos separados em `orchestrator/fixtures/rag/explore/mini-q02/`:

1. `classificacao-cega.yaml`: contém apenas código (`r01`…`r40`), `pergunta_id`, `pergunta`, `resposta` (`resposta_crua`), `classe: null` e `observacao: ""` **[→ Emenda E-M01: mais só o campo `elo` no topo; nada de semente]**. **Não** contém versão (`v1`/`v4`), hash de regras, ordem de execução, número da amostra, custo, tempo nem trechos.
2. `mapa-cego.json`: contém o mapa `código → {versao, pergunta_id, amostra, indice_execucao, regras_sha256}`, a semente usada e o `sha256` do `respostas.json` **[→ Emenda E-M01: mais o `elo`; o mapa não é aberto nem colado até as 40 classes]**.

Quem classifica **[→ Emenda E-M01: o Claude no chat, recebendo só o YAML colado pelo Max]** vê apenas a pergunta e a resposta e marca uma das 3 classes por item:

- **`q02`:** `RECUSA` (certo) | `ACEITA` (errado) | `AMBÍGUA` (não conclui ou conclui as duas coisas).
- **`q04`:** `NÃO TROCA` (certo) | `TROCA` (errado) | `AMBÍGUA`.

**Regra para `AMBÍGUA`:** a resposta não deixa claro o que o funcionário deve fazer **AGORA** com aquele produto. `"Sim, se estiver dentro de 24 h"` para uma compra de anteontem conta como **`TROCA` (errado)**, não como `AMBÍGUA`.

O `--resultado` só calcula o veredito depois que **todas as 40 respostas** estiverem marcadas com classes válidas.

## 5. Critérios de decisão pré-registrados

A proposta **`v4` passa no sinal** se e somente se a comparação for íntegra **E TODAS** as 3 condições abaixo forem verdadeiras:

1. **`q02`:** erros da `v4` (`ACEITA` + `AMBÍGUA` + falhas **[→ Emenda E-B03: "falhas" = só fora do RAG; falha de infra invalida a coleta]**) `≤ 1` em 10, **E** estritamente menos erros que a `v1` (`erros_v4_q02 < erros_v1_q02`).
   - **Caso especial (`v1` com 0 erros na `q02`):** se a `v1` errar `0` de `10` na `q02`, registra-se que o erro não apareceu nesta amostra e que o critério 1 não decide nada (**sem conclusão sobre a q02**; não passa no sinal).
2. **`q04`:** erros da `v4` (`TROCA` + `AMBÍGUA` + falhas **[→ Emenda E-B03: "falhas" = só fora do RAG]**) `= 0` em 10.
3. **Sem falso "não cobre" na `v4`:** nenhuma resposta da `v4` diz que o manual não cobre o assunto quando os trechos recebidos trazem a regra.
   - *Definição operacional congelada:* "os trechos recebidos trazem a regra" significa que todas as seções-fonte esperadas da pergunta no `gabarito.yaml` (`POP` + título de seção normalizado) estão presentes em `trechos`. "Diz que o manual não cobre o assunto" detecta a frase exata `"O manual de procedimentos não cobre isso."` ou afirmação explícita de ausência de cobertura pelo manual ~~(`manual [de procedimentos] não cobre/trata/aborda/contempla` ou `não cobre isso/esse/essa/este/esta/o assunto/a situação/o caso/especificamente`)~~ **[→ Emenda E-B02: lista ampliada]**, evitando falsos positivos em negativas corretas como `"o manual não prevê troca após o prazo"`.

**Regra de falhas:**
- Falha de infraestrutura (`falha_de_infra = True`) ~~conta como **erro** naquela amostra, sem nova rodada~~ **[→ Emenda E-B03: depois da 1ª chamada, QUALQUER falha de infra PARA a coleta e a torna INVÁLIDA; uma nova coleta completa]** (se ocorrer logo na 1ª chamada do experimento, o script aborta sem gravar nada **[→ Emenda E-B03: repetir uma vez, registrando]**). **[→ Emenda E-B03: coleta *abortada* no meio = resultado INVÁLIDO]**
- Pergunta que não foi ao `specialist_rag` (`rag_acionado = False`) conta como **erro** e fica listada explicitamente no relatório.

## 6. Projeção de custo e orçamento máximo

Baseada no custo real medido na Missão 10 (`v1`, `fixtures/rag/m10/respostas-v1-r1.json` e `respostas-v1-r2.json`):

- Média real `v1` na `q02`: `US$ 0,001731` por resposta; na `q04`: `US$ 0,001883` por resposta (média do par: `~US$ 0,001807`/resposta).
- 20 respostas `v1` (10 `q02` + 10 `q04`): `~US$ 0,0361`.
- 20 respostas `v4`: base `v1` (`US$ 0,0361`) + entrada extra da Regra 6 (+1.692 caracteres ≈ 564 tokens/chamada no `synthesize_final` a US$ 0,2574/1M tokens = `+US$ 0,000145`/resposta, `+US$ 0,0029` nas 20) = `~US$ 0,0391`.
- **Total projetado (40 respostas, sem juiz):** **`~US$ 0,075`**.
- **Orçamento máximo:** **`US$ 0,10`** no total. O CLI recusa qualquer `--orcamento > 0.10` ou `<= 0` e interrompe a coleta caso o acumulado ultrapasse o orçamento **[→ Emenda E-B03: o corte vem depois da resposta que estoura; coleta abortada = INVÁLIDO]**.

## 7. Comandos (executar a partir de `orchestrator/`)

```bash
# 1. Plano grátis (confere hashes, índice e projeção de custo; nada executado)
.venv/bin/python -m orchestrator.rag.mini_q02

# 2. Coleta paga (40 respostas intercaladas, teto US$ 0,10)
.venv/bin/python -m orchestrator.rag.mini_q02 --executar --orcamento 0.10

# 3. Gerar arquivo de classificação cega + mapa separado (grátis)
.venv/bin/python -m orchestrator.rag.mini_q02 --classificar-arquivo

# 4. ~~(Manual/cego) Preencher `classe` nos 40 itens de fixtures/rag/explore/mini-q02/classificacao-cega.yaml~~
#    [-> Emenda E-M01] O Max cola SO o conteudo de classificacao-cega.yaml no chat; o Claude preenche `classe`
#    nos 40 itens; o Max confere. mapa-cego.json e respostas.json ficam fechados ate la.

# 5. Calcular resultado oficial pelos critérios 1–3 (grátis)
.venv/bin/python -m orchestrator.rag.mini_q02 --resultado
```

## 8. Resultado

~~*Ainda não executado (pré-registro congelado antes da coleta).*~~ **Executado em 21/11/2026** (coleta 1, abaixo). **Veredito: `v4` NÃO passa no sinal.** Conclusão na §11.

### Registro de coletas (Emenda E-B03)

Cada coleta INVÁLIDA (por infra, orçamento ou interrupção) e cada FalhaInicial entram aqui, com data, tipo do erro e a amostra em que parou.

**Coleta 1 — 21/11/2026, 22:30:10 → 22:36:39 (−03:00): coleta concluída, sem falha de infra.**

- 40/40 respostas, todas pelo RAG (`rag_acionado = True`), nenhuma `falha_de_infra`, sem aborto por orçamento; nenhuma FalhaInicial (`falha-inicial.json` não existe); `coletas.json`: `estado = "concluida"`.
- **Custo: US$ 0,0744** (v1 US$ 0,0361; v4 US$ 0,0382; projetado US$ 0,0752).
- Código da coleta: commit `ca5ff24` (pré-registro `f963470b…`, `mini_q02.py`, testes e `regras-proposta.txt` idênticos ao commit). O `respostas.json` registra `git.sujo = true`: o único arquivo fora do git no momento era o próprio `fixtures/rag/explore/` (o `coletas.json` é gravado antes da 1ª chamada, e o `git status --porcelain` conta diretório não rastreado).
- Classificação cega feita pelo Claude no chat, recebendo só o `classificacao-cega.yaml`; conferida pelo Max; o mapa só foi aberto depois das 40 classes.

Saída literal do `--resultado` (`.venv/bin/python -m orchestrator.rag.mini_q02 --resultado`, de dentro de `orchestrator/`, código de saída 0):

```text
| Pergunta | Versão | Certo | Errado (classe) | AMBÍGUA | Infra | Fora do RAG | Erros totais | Falso "não cobre" |
|---|---|---|---|---|---|---|---|---|
| q02 | v1 | 3 (RECUSA) | 7 (ACEITA) | 0 | 0 | 0 | 7/10 | 1 |
| q02 | v4 | 4 (RECUSA) | 6 (ACEITA) | 0 | 0 | 0 | 6/10 | 0 |
| q04 | v1 | 7 (NÃO TROCA) | 0 (TROCA) | 3 | 0 | 0 | 3/10 | 0 |
| q04 | v4 | 7 (NÃO TROCA) | 2 (TROCA) | 1 | 0 | 0 | 3/10 | 0 |

- 1) q02 (v4 ≤ 1/10 e v4 < v1): NÃO (v4=6/10, v1=7/10)
- 2) q04 (v4 = 0/10): NÃO (v4=3/10, v1=3/10)
- 3) nenhum falso "não cobre" na v4 (com regra nos trechos): sim
- Latência do synth (informativo, não decide): v1 p50 3.89 s / p95 6.55 s (n=20); v4 p50 4.79 s / p95 7.01 s (n=20)

**Veredito pelo pré-registro: v4 NÃO passa no sinal.** Custo total medido: US$ 0.0744 (semente cega: 198225672132207420102100123204455784365).
```

### Tabela de conferência (mapa aberto depois das 40 classes)

Junta `mapa-cego.json` (código → versão, pergunta, amostra) e `classificacao-cega.yaml` (classe e observação do classificador). Qualquer um pode refazer a contagem do `--resultado` a partir dela.

| Código | Versão | Pergunta | Amostra | Classe | Observação do classificador |
|---|---|---|---|---|---|
| r01 | v1 | q04 | 4 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |
| r02 | v4 | q04 | 3 | NÃO TROCA |  |
| r03 | v4 | q04 | 8 | NÃO TROCA |  |
| r04 | v4 | q02 | 6 | ACEITA |  |
| r05 | v4 | q02 | 9 | ACEITA |  |
| r06 | v4 | q04 | 9 | TROCA |  |
| r07 | v1 | q02 | 5 | ACEITA |  |
| r08 | v4 | q02 | 10 | ACEITA |  |
| r09 | v1 | q02 | 7 | ACEITA |  |
| r10 | v4 | q02 | 2 | ACEITA |  |
| r11 | v4 | q04 | 1 | NÃO TROCA |  |
| r12 | v1 | q02 | 1 | ACEITA |  |
| r13 | v4 | q04 | 2 | NÃO TROCA |  |
| r14 | v1 | q02 | 9 | RECUSA |  |
| r15 | v4 | q02 | 4 | RECUSA |  |
| r16 | v1 | q04 | 5 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |
| r17 | v4 | q02 | 1 | RECUSA |  |
| r18 | v4 | q04 | 4 | NÃO TROCA |  |
| r19 | v1 | q02 | 8 | ACEITA |  |
| r20 | v4 | q04 | 6 | TROCA | comeca por Sim, pode trocar e depois diz que passou do prazo |
| r21 | v1 | q04 | 10 | AMBÍGUA | nao aplica anteontem ao prazo de 24 h |
| r22 | v1 | q02 | 4 | RECUSA |  |
| r23 | v1 | q04 | 6 | AMBÍGUA | nao diz que anteontem passou; manda trocar se dentro de 24 h |
| r24 | v4 | q04 | 5 | NÃO TROCA |  |
| r25 | v4 | q04 | 10 | AMBÍGUA | comeca por Sim; diz que defeito permite troca sem limite de 24 h (errado) |
| r26 | v4 | q02 | 7 | RECUSA |  |
| r27 | v1 | q02 | 10 | ACEITA |  |
| r28 | v4 | q02 | 3 | ACEITA |  |
| r29 | v1 | q02 | 3 | RECUSA |  |
| r30 | v4 | q02 | 8 | RECUSA |  |
| r31 | v4 | q02 | 5 | ACEITA |  |
| r32 | v1 | q02 | 2 | ACEITA |  |
| r33 | v1 | q04 | 3 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |
| r34 | v1 | q04 | 1 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |
| r35 | v1 | q02 | 6 | ACEITA | aceita; e diz 'o manual nao menciona' (possivel criterio 3) |
| r36 | v1 | q04 | 8 | AMBÍGUA | pode nao ser possivel: nao conclui |
| r37 | v1 | q04 | 7 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |
| r38 | v1 | q04 | 9 | NÃO TROCA |  |
| r39 | v4 | q04 | 7 | NÃO TROCA |  |
| r40 | v1 | q04 | 2 | NÃO TROCA | lista sem Nao explicito, mas afirma que o prazo de 24 h ja passou |

## 9. Emenda de 21/11/2026, antes de qualquer medição, após revisão adversária do Claude Code

Feita **antes de qualquer execução paga** (nenhuma resposta coletada; `fixtures/rag/explore/mini-q02/` não existe). A `v1`, a `v4` (`regras-proposta.txt`), as perguntas, o `N`, a ordem, as classes e os critérios 1 e 2 **não mudam**; os hashes da §2 continuam valendo. O que muda:

### E-M01 — a semente revelava as versões (cegueira)

- **Por quê:** com a semente fixa (`20261121`), impressa no próprio YAML, e a ordem de execução pública (`sequencia_execucao()`), `random.Random(semente).shuffle` reconstruía a versão de **40/40** códigos sem abrir o mapa nem o `respostas.json`.
- **Mudou:** o `--classificar-arquivo` sorteia a semente com o módulo `secrets` (128 bits) e a grava **só** no `mapa-cego.json`, nunca no YAML. O elo entre o YAML e o mapa passa a ser um token aleatório (`secrets.token_hex(16)`, campo `elo`), que não é a semente nem nada derivável do código. A flag `--semente` saiu do CLI. O YAML cego fica só com `elo` e, por item, `codigo`, `pergunta_id`, `pergunta`, `resposta`, `classe` e `observacao`. O `--resultado` invalida se o `elo` faltar ou divergir entre os dois arquivos. O log do `--classificar-arquivo` não imprime semente nem elo.
- **Regra nova de classificação:** a classificação é feita pelo **Claude no chat**, que recebe **só** o conteúdo do `classificacao-cega.yaml` colado pelo Max, sem acesso ao mapa nem ao `respostas.json`. O Max confere depois. O `mapa-cego.json` **não é aberto nem colado em lugar nenhum** até as 40 classes estarem preenchidas. A classificação acontece num chat **sem ferramentas de arquivo sobre este repositório** (ex.: claude.ai sem o repo); numa sessão do Claude Code, que pode abrir o mapa, a cegueira voltaria a depender só de confiança. O YAML preenchido volta com `elo`, `codigo` e `pergunta_id` intactos e é salvo por cima do `classificacao-cega.yaml`; qualquer divergência invalida o `--resultado`.
- **Teste:** o ataque da revisão virou teste (`test_m01_ataque_da_semente_nao_reconstroi_as_versoes`): testando como semente todo inteiro do YAML, o elo e todo literal inteiro do código-fonte, não reconstrói; com a semente vazada (controle positivo) acerta 40/40.

### E-B01 — guardas de integridade sem teste do caminho de falha

- **Por quê:** 8 mutantes sobreviviam (ordem intercalada, `indice_meta` da M8, hash das regras por resposta, etapa 2, `abortado_por_orcamento`, grade 2×2×10, regex do critério 3, escopo do critério 3 só na `v4`).
- **Mudou:** só testes (nenhuma regra muda): cada guarda é quebrada sozinha e o `--resultado` precisa dar INVÁLIDO com exatamente aquele problema. O mutante "sem a guarda *v1 com 0 erros*" é **equivalente** (`erros_v4 < 0` nunca é verdade) e só fica registrado.

### E-B02 — detector de "não cobre" (critério 3) ampliado

- **Por quê:** a definição original deixava passar formas comuns de dizer que o manual não cobre.
- **Mudou:** "diz que o manual não cobre o assunto" passa a ser, no texto normalizado (sem acento, minúsculas), a frase exata `"O manual de procedimentos não cobre isso."` **ou** qualquer uma destas:
  1. sujeito `manual [de procedimentos]` / `POP[-XX]` / `procedimento` / `trecho(s) [recebidos | do manual]` + `não` + `cobre(m) / trata(m) / aborda(m) / contempla(m) / menciona(m) / especifica(m)` — cobre "o manual não menciona", "os trechos não cobrem", "o POP não cobre";
  2. `não cobre(m) isso/esse/essa/este/esta/o assunto/a situação/o caso/especificamente` (original);
  3. `não especifica(m)` (mesmo sem sujeito);
  4. `não encontrei` seguido, na mesma frase (até 60 caracteres), de `manual`, `trecho(s)` ou `POP` — "não encontrei no manual";
  5. `não há informação` / `não há informações`;
  6. `não consta(m) no/nos/na/nas/em` + `manual`, `trecho(s)`, `POP` ou `procedimento` — "não consta no manual".
- **Continua fora, de propósito:** `não prevê`, `não permite`, `não aceita`, `não é possível`, `não há troca` etc. — negativas corretas como `"o manual não prevê troca após o prazo"` (resposta certa da `q04` na M10, `m10/respostas-v1-r2.json`) **não** disparam.
- **Custo medido da ampliação, em dados reais (M8–M10, 143 respostas com a regra nos trechos):** nenhuma resposta da `q02`/`q04` dispara; entram 2 disparos novos, ambos na `q11` (avisos parciais: "o manual não especifica o uso de cloro puro", "não há informação específica sobre tempo de molho"). Ou seja: um aviso parcial sobre um detalhe também conta como "não cobre". Fica aceito assim.

### E-B03 — coleta abortada, parada por infra (K = 1) e FalhaInicial

- **Por quê:** o pré-registro não dizia o que fazer com uma coleta interrompida. Erros de LLM e do grafo viravam falha por amostra (`av.responder_pergunta` captura a exceção e devolve `falha_de_infra = True`, e a coleta seguia): uma queda do provedor que durasse o resto da coleta gerava erros em todas as amostras seguintes e um resultado **válido** que reprovava a `v4` por infraestrutura, não pela regra. Além disso, uma exceção que escapasse, um Ctrl+C, um `kill` ou uma queda de energia faziam o script parar **sem gravar nada** (dinheiro gasto, fato não registrado), e nada impedia uma nova coleta paga — nem com outro `--saida`.
- **Regra de parada (decisão do Max, K = 1):** **qualquer** falha de infraestrutura em **qualquer** amostra **depois da 1ª chamada** — exceção do grafo, erro do provedor, timeout, amostra marcada como falha pelo `av.responder_pergunta` (`falha_de_infra = True`) ou exceção que escape dele — faz a coleta **parar na hora**. O que já foi coletado é gravado (inclusive a amostra que falhou), com `abortado_por_infra = {indice_execucao, id, versao, amostra, erro_tipo}`; o resultado é **INVÁLIDO** e a coleta fica registrada. O registro guarda só o **tipo** do erro, nunca a mensagem do provedor. **Falha de infra deixa de contar como "erro daquela amostra": ela agora sempre invalida** (o `--resultado` também invalida qualquer `respostas.json` com uma resposta `falha_de_infra = True`).
- **Uma nova coleta por infra:** uma coleta INVÁLIDA por infra dá direito a **UMA** nova coleta **completa** (as 40 respostas do zero, com uma **nova** `--saida`). Ela é registrada na §8 com a data, o tipo do erro e a amostra em que parou (o `--executar` imprime a linha pronta, `REGISTRAR NO PRÉ-REGISTRO`). Uma **2ª** coleta INVÁLIDA por infra **encerra a exploração sem resultado**. Não há 3ª.
- **Orçamento não é infra:** coleta abortada por orçamento continua **INVÁLIDA sem direito a nova coleta**.
- **Pergunta fora do RAG** (`rag_acionado = False`) não é infra: continua contando como **erro** daquela amostra (§5), sem parar a coleta.
- **FalhaInicial (inalterada):** a 1ª chamada falhou e nada foi gravado. Pode repetir **uma vez**. Cada uma fica registrada em `fixtures/rag/explore/mini-q02/falha-inicial.json` (estado `falha_inicial`, tentativa, data, tipo do erro).
- **Contadores separados, cada um vale uma vez só:** a FalhaInicial (`falha-inicial.json`, no máximo 2 tentativas) e a nova coleta por infra (`coletas.json`, no máximo 2 coletas) **não se somam**: uma FalhaInicial não consome a nova coleta por infra, e a nova coleta por infra não consome a repetição da FalhaInicial (inclusive se a FalhaInicial acontecer na própria nova coleta).
- **Registro fixo de coletas** (`fixtures/rag/explore/mini-q02/coletas.json`, numa pasta **fixa**, que não depende de `--saida`): cada coleta entra como `iniciada` **antes** da 1ª chamada paga e termina num destes estados:
  - `concluida` — coleta completa; nenhuma nova coleta;
  - `invalida_infra_1a` — INVÁLIDA por infra (1ª vez); **é o único estado que libera o `--executar`** (a nova coleta completa);
  - `invalida_infra_2a_encerra` — INVÁLIDA por infra (2ª vez); exploração encerrada sem resultado;
  - `invalida_orcamento` — INVÁLIDA por orçamento; sem nova coleta;
  - `iniciada` (sem fim) — interrompida sem registro (Ctrl+C, `kill`, queda de energia) = INVÁLIDA; sem nova coleta.
  A FalhaInicial e o erro de pré-checagem (hash, índice, orçamento, antes de qualquer chamada) tiram a coleta `iniciada` do registro, porque nenhuma resposta paga foi gravada.
- **Esclarecimento do teto:** o corte de orçamento acontece **depois** da resposta que estoura, então o gasto pode passar de US$ 0,10 em no máximo uma resposta (~US$ 0,002, teto efetivo ~US$ 0,102 por coleta). Com a nova coleta por infra, o gasto máximo da exploração fica em ~US$ 0,20.

## 10. Limites conhecidos

- **L1 (B-04) — configuração da busca não travada:** busca, `top_k`, rerank e modelos são lidos do `.env`/shell e não entram na checagem de integridade (mesmo padrão da M9 e da M10). Na revisão o `.env` não definia nenhum desses campos e o plano real mostrou híbrido, `top_k` 5, sem rerank, `deepseek/deepseek-chat` e `indice_meta` igual ao da M8. Conferir na saída do plano antes do `--executar`.
- **L2 (B-05) — hash declarado, não medido:** o `regras_sha256` de cada resposta é o hash do texto **pretendido**, não do que o `synthesize_final` recebeu de fato. A fiação está provada por teste (o espião do synth mata o mutante "v4 nunca injetada"; `nodes.py` lê `rag_specialist.regras_da_etapa1()` pelo módulo), mas a coleta real não grava o prompt efetivo.
- **L3 (B-06) — sinal dentro da amostra que desenhou a regra:** o texto da `v4` passa na regra anti-decoreba literal (nenhum produto, número de caso ou situação das 6 perguntas de treino), mas cada sub-regra é o molde de uma pergunta de treino: 6a → `q02`; 6b → `q04` e `q05`; 6c → `q01`; 6d → `q09` e `q10`. **Este mini-teste mede a `q02` e a `q04` dentro da amostra que desenhou a regra: um bom resultado aqui não mostra generalização. Só a prova10 lacrada mede generalização.**

## 11. Conclusão

### Medido (coleta 1, 21/11/2026, `deepseek/deepseek-chat`, N = 10 por pergunta por versão)

- **q02 (frango congelado a −10 °C; o certo é recusar):** a `v1` **aceitou em 7 de 10** (r07, r09, r12, r19, r27, r32, r35); a `v4` **aceitou em 6 de 10** (r04, r05, r08, r10, r28, r31). Nenhuma resposta AMBÍGUA. O critério 1 exigia `v4 ≤ 1/10`: **reprovado**.
- **q04 (queijo comprado anteontem; o certo é não trocar):** a `v4` teve **2 "TROCA", e as duas começam por "Sim"**:
  - **r06** (`v4`, amostra 9): *"Sim, o cliente pode trocar o queijo, desde que o produto tenha sido comprado há 24 horas ou menos e esteja na embalagem original, mantido na temperatura indicada."*
  - **r20** (`v4`, amostra 6): *"Sim, o cliente pode trocar o queijo, desde que a solicitação seja feita dentro do prazo de **24 horas** a partir do horário impresso no cupom."*
  
  A `v1` teve **nenhum** "TROCA" (e nenhuma resposta da `v1` na `q04` começa por "Sim"). Erros totais iguais (3/10 em cada): a `v1` errou por **AMBÍGUA** (r21, r23, r36); a `v4`, por 2 TROCA + 1 AMBÍGUA (r25, que também começa por "Sim"). O critério 2 exigia `v4 = 0/10`: **reprovado**.
- **Critério 3:** nenhum falso "não cobre" na `v4`. A `v1` teve 1 (r35, só informativo; não decide).
- **Veredito pelo pré-registro: `v4` NÃO passa no sinal.** A `v4` não vai para a Missão 11 como está.
- **A exploração com o Gemini não reproduziu o erro:** na Rodada 0 (`subagentes-q02.md`, §1), o Gemini acertou a `q02` **3 de 3** com a `v1`; o `deepseek-chat`, com o mesmo texto de regras, acertou **3 de 10**.
- Informativo (não decide): latência do synth `v1` p50 3,89 s / p95 6,55 s; `v4` p50 4,79 s / p95 7,01 s.

### Hipótese (não medida aqui)

- **O `deepseek-chat` não compara números negativos de forma confiável, e a instrução no prompt não muda isso.** A Regra 6a explica o sinal de menos e a `v4` ainda aceitou −10 °C contra o limite de −12 °C em 6 de 10; a diferença para a `v1` (7 → 6) é de uma amostra em 10 e não distingue as duas versões.
- Leitura secundária, também não medida: a Regra 6c ("comece por Sim ou Não") parece ter puxado respostas da `q04` para começar por "Sim" (r06, r20, r25), trocando AMBÍGUA por TROCA.
- O que isso sugere — e só uma nova missão, com pré-registro próprio, pode medir — é que a comparação numérica deveria sair do texto do prompt (por exemplo, uma checagem determinística em código ou outro modelo no synth), e que a prova10 lacrada continua intocada.
