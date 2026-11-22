# Exploração com Subagentes (Sem API) — Diagnóstico de Perguntas Sim/Não com Limite ou Prazo

Data: `2026-11-21`
Ambiente: Subagentes isolados (`agente_rag`, `juiz_rag`, `detetive_rag`) rodando com Gemini 4 Argon (High), **zero chamadas de API paga** (`OpenRouter` não utilizado, `.env` não lido, pasta `lacre/` e arquivos `prova10` não acessados).

---

## 0. Desenho Experimental e Material Utilizado

- **Perguntas de treino (6):** `q02`, `q04` (Ciclo 1) + `q10`, `q01` (Ciclo 2) + `q05`, `q09` (Ciclo 3).
- **Gabarito e resposta esperada:** `orchestrator/fixtures/rag/gabarito.yaml`.
- **Fatos-chave obrigatórios:** `orchestrator/fixtures/rag/fatos_chave_v1.yaml`.
- **Trechos de contexto:** os mesmos 5 trechos por pergunta gravados em `orchestrator/fixtures/rag/m10/respostas-v1-r1.json`.
  - **Nota metodológica sobre a `q10` (alinhada previamente com o Max):** em `respostas-v1-r1.json`, a `q10` (*"fechei o caixa faltando 3 reais, vou ter problema?"*) foi a única das 17 perguntas com fonte em que a busca híbrida falhou no recall@5 (a seção `"6. Diferença de caixa"` do `POP-04` ficou na 7ª posição e não entrou nos 5 trechos recuperados). Sem esse trecho, seria impossível avaliar o raciocínio de comparação de limite (`R$ 3,00` vs. tolerância de `até R$ 5,00`) e exigir o fato-chave `"R$ 5"` sem violar a proibição de inventar dados fora dos trechos. Por decisão do Max antes da Rodada 0, o trecho `POP-04, seção "6. Diferença de caixa"` (copiado literalmente do próprio `respostas-v1-r1.json`, onde aparece na `q06` trecho 3) entrou na posição `n=5` da `q10` (substituindo `POP-04, seção "3. Pagamentos aceitos"`), mantendo 5 trechos em todas as perguntas.
- **Isolamento dos 3 papéis:**
  - `agente_rag`: recebe exclusivamente `_SYNTHESIZE_SYSTEM_PROMPT` + `REGRAS_DO_MANUAL` (v1 na Rodada 0; proposta nos Ciclos 1 a 3), a pergunta e os 5 trechos delimitados com `<trecho ... marca="...">`. Não vê gabarito, não vê fatos-chave e é proibido de invocar qualquer ferramenta. Cada amostra roda em uma instância de subagente independente (`conversationId` próprio).
  - `juiz_rag`: recebe a pergunta, a resposta do `agente_rag`, a `resposta_esperada`, os `fatos_chave` e os trechos. Aplica o critério triplo estrito: **(1) conclusão certa (Sim/Não explícito ou ação correta para o caso concreto) + (2) todos os fatos-chave presentes + (3) nada inventado fora dos trechos**.
  - `detetive_rag`: recebe as respostas que falharam (da Rodada 0 e também do histórico de `m9`/`m10`) e diagnostica, com citação literal, onde o raciocínio quebrou.

---

## 1. Rodada 0 — Linha de Base (Prompt Atual `v1`)

- **Texto das regras:** `REGRAS_DO_MANUAL` v1 original (`sha256: 3f4ca553845cc40ed10451f70df9357f2afad2ac2f76d265198be0e6be498240`), sem alterações.
- **Amostras:** 6 perguntas × 3 amostras independentes = **18 amostras**.

### Resultado por pergunta na Rodada 0

| Pergunta | Resultado (Amostras) | Passou 3/3? | Resumo do comportamento da `v1` com Gemini |
|---|---|---|---|
| **q02** (frango congelado a `-10 °C`, aceito?) | **3/3** (`PASSA`, `PASSA`, `PASSA`) | **Sim** | Nas 3 amostras concluiu `"Não, você deve recusar"`, comparou `-10 °C` com o limite de `até −12 °C` e citou o `F-07`. |
| **q04** (queijo comprado `anteontem`, posso trocar?) | **3/3** (`PASSA`, `PASSA`, `PASSA`) | **Sim** | Nas 3 amostras concluiu `"Em regra, não pode trocar"` / `"não é possível realizar a troca"` (observando que `anteontem` > `24 horas`), citou `24 horas` e explicou a exceção de produto vendido já vencido. *(Nota: nenhuma das 3 amostras começou pela palavra `"Não"` na 1ª posição; todas abriram com `"Em regra, não..."`.)* |
| **q10** (caixa faltando `3 reais`, vou ter problema?) | **3/3** (`PASSA`, `PASSA`, `PASSA`) | **Sim** | Nas 3 amostras começou com `"Não, você não terá problema(s)"`, comparou `R$ 3,00` com a tolerância de `até R$ 5,00` e citou o `F-02`. |
| **q01** (caminhão chegou às `15h`, posso receber?) | **2/3** (`PASSA`, `PASSA`, **`FALHA`**) | **NÃO** | As amostras 1 e 2 abriram com `"Não diretamente, pois..."`. A **Amostra 3 falhou**: omitiu o `"Não"` e abriu direto pela condição de exceção (`"Você só poderá receber o caminhão mediante autorização..."`). |
| **q05** (shampoo comprado `semana passada`, lacrado, dá pra trocar?) | **1/3** (**`FALHA`**, `PASSA`, **`FALHA`**) | **NÃO** | A amostra 2 abriu com `"Sim, ainda dá para trocar, desde que ainda esteja dentro do prazo de até 7 dias corridos..."`. As **Amostras 1 e 3 falharam**: omitiram a conclusão `"Sim"` esperada pelo gabarito e abriram de forma evasiva com `"Depende de quantos dias exatos..."` / `"Depende da data exata da compra..."`. |
| **q09** (gaveta com `quase 900 conto`, faço o que?) | **3/3** (`PASSA`, `PASSA`, `PASSA`) | **Sim** | Nas 3 amostras identificou que ultrapassou `R$ 800,00`, indicou bloqueio do PDV e acionamento do `fiscal de caixa` para fazer a `sangria` deixando o fundo de troco de `R$ 200,00`, sem errar conta de subtração. |

- **Saldo da Rodada 0:** **4 de 6 perguntas** fecharam 3/3 (`q02`, `q04`, `q10`, `q09`); **2 de 6 perguntas falharam** (`q01` com 2/3 e `q05` com 1/3). No total de amostras, **15/18 (83,3%)** passaram e **3/18 falharam**.

### Frases literais das respostas que falharam na Rodada 0 e Diagnóstico do DETETIVE

1. **Falha na `q01` — Amostra 3 (`conversationId: e0dea26f-eae8-4481-8a86-fca99482aabf`):**
   - **Citação literal da resposta do AGENTE:**
     > `"Você só poderá receber o caminhão mediante **autorização por escrito do gerente de loja**, registrada no **Formulário F-03 (Recebimento Extraordinário)** (POP-01, seção "2. Horário da doca"). Isso ocorre porque às 15h a entrega está fora do horário padrão da doca (POP-01, seção "2. Horário da doca"): - **Segunda a sábado:** das **6h às 14h**."`
   - **Veredito do JUIZ:** `FALHA — Omite a conclusão negativa explícita ("Não") ao responder "posso receber?", iniciando diretamente pela condição de exceção.`
   - **Diagnóstico do DETETIVE (`8e54c4ee-56c0-4480-a9c8-6a0923ebe719`):**
     O agente **colocou a exceção na frente da regra padrão aplicável e omitiu a conclusão negativa explícita ("Não")**. Diante de uma pergunta fechada (*"chegou agora 15h, posso receber?"*) em que o horário viola o limite padrão (`15h > 14h`), o modelo saltou o veredito negativo da regra geral e começou pela cláusula de exceção (`Formulário F-03`). É exatamente a mesma falha apontada pelo Max na calibração humana da `q01` na Missão 8 (`docs/RAG.md`: *"a resposta não diz 'não' antes das condições"*).

2. **Falhas na `q05` — Amostra 1 (`1ce0a073-a1e4-456d-b1f7-9eed0daeaeda`) e Amostra 3 (`21ce1607-5571-4618-b515-9e7001830327`):**
   - **Citações literais das respostas do AGENTE:**
     - *Amostra 1:*
       > `"Depende de quantos dias exatos se passaram desde a compra: * Para produtos não perecíveis (o que inclui itens de **higiene**, como shampoo), a troca por **arrependimento** é aceita em até **7 dias corridos** após a compra, desde que o produto esteja **em perfeito estado e lacrado** (POP-03, seção "4. Prazo de troca — produtos não perecíveis")."`
     - *Amostra 3:*
       > `"Depende da data exata da compra: a troca ainda pode ser feita se ainda estiver dentro do limite de **7 dias corridos** a partir do dia em que ela comprou."`
   - **Veredito do JUIZ:** `FALHA — Inicia com "Depende" e omite a conclusão explícita "Sim" exigida para o caso perguntado.`
   - **Diagnóstico do DETETIVE (`8e54c4ee-56c0-4480-a9c8-6a0923ebe719`):**
     O agente **substituiu o veredito afirmativo condicional (`"Sim, se / desde que..."`) por uma abertura evasiva (`"Depende..."`)**. Embora todas as condições explícitas na pergunta fossem compatíveis com a troca (produto não perecível de higiene não íntima e lacrado: *"nem abriu e não gostou"*), a expressão temporal *"semana passada"* é imprecisa (pode ser $\le 7$ dias ou $> 7$ dias). Sem uma regra sobre como concluir perguntas de Sim/Não quando o prazo citado pelo usuário é impreciso, o modelo hesita e abre com `"Depende"` em vez de `"Sim, desde que esteja dentro de 7 dias corridos"`.

---

## 2. O Padrão Escondido (Rodada 0 + Falhas Reais de `m9` e `m10`)

O diagnóstico do `detetive_rag` cruzou as falhas da Rodada 0 no Gemini com as falhas reais do modelo de produção (`deepseek/deepseek-chat`) gravadas em `orchestrator/fixtures/rag/m9/` e `m10/`:

1. **Inversão de grandeza em números negativos (`q02` em `v1`, `v2` e `v3`):**
   - **Citação literal 1 (`m10/respostas-v1-r2.json`, `q02`):**
     > `"Com base no manual de procedimentos, o frango congelado marcando -10 °C no termômetro **deve ser aceito**, pois está dentro da faixa permitida para congelados, que é de até -12 °C (POP-01, seção "4. Temperatura na chegada")."`
   - **Citação literal 2 (`m10/respostas-v3-r1.json`, `q02`, `resposta_etapa1` com regras `v1`):**
     > `"De acordo com o manual de procedimentos, o frango congelado marcando -10 °C no termômetro **deve ser aceito**, pois a temperatura máxima permitida para congelados na chegada é de -12 °C (POP-01, seção "4. Temperatura na chegada")."`
   - **Citação literal 3 (`m9/respostas-v2-r2.json`, `q02`):**
     > `"Sim, o frango congelado a -10°C pode ser aceito (POP-01, seção "4. Temperatura na chegada"). A temperatura máxima para congelados é -12°C. Verifique também sinais de descongelamento."`
   - **Onde o raciocínio quebrou:** Em todas as categorias positivas da tabela (`7 °C`, `10 °C`, `8 °C`), `"Aceitar até X"` significa que um número de menor módulo (`< X`) é mais frio e aceito. Quando o limite é negativo (`−12 °C`), a expressão `"até −12 °C"` induz o modelo sem cadeia de pensamento a comparar o número **sem o sinal** (`10 < 12` $\implies$ "10 está até 12"), esquecendo que na escala negativa **quanto menor o número sem o sinal, MAIOR (mais quente) é a temperatura real** ($-10\text{ °C} > -12\text{ °C}$, logo está **acima** do limite máximo de $-12\text{ °C}$ e deve ser **recusado**). Além disso, o modelo escreve a conclusão (`"deve ser aceito"` / `"Sim"`) **antes** de enunciar o limite do manual e compará-lo ao valor da pergunta.

2. **Não conversão de expressão de tempo relativa antes do veredito (`q04` na `v2`):**
   - **Citação literal 4 (`m9/respostas-v2-r1.json`, `q04`):**
     > `"Sim, troca em até 24h para perecíveis, com embalagem original (POP-03, seção "3. Prazo de troca — produtos perecíveis"). O queijo deve estar na embalagem original e dentro do prazo."`
   - **Citação literal 5 (`m9/respostas-v2-r2.json`, `q04`):**
     > `"Sim, se o produto estiver dentro do prazo de 24 horas (POP-03, seção "3. Prazo de troca — produtos perecíveis")."`
   - **Onde o raciocínio quebrou:** Ao ser obrigado a colocar `"Sim"` ou `"Não"` na 1ª palavra sem instrução de conversão temporal, o modelo viu que o manual permite troca de perecíveis (`"até 24 horas"`), emitiu `"Sim"` no primeiro token e tratou o prazo como condição em aberto (`"se estiver dentro do prazo de 24 horas"`), deixando de converter o dado fechado da pergunta (`"anteontem"` $\approx 48\text{ horas}$) para a unidade da regra ($48\text{ h} > 24\text{ h} \implies \text{"Não"}$).

3. **Inversão entre regra padrão e exceção ou hesitação diante de prazo impreciso (`q01` e `q05` na `v1`, tanto no DeepSeek quanto no Gemini):**
   - Na `q01` (`m10/respostas-v1-r1.json` e `Rodada 0 q01 a3`), como existe uma exceção no manual (autorização do gerente no `F-03`), o modelo omite o `"Não"` da regra padrão (`15h` está fora de `6h às 14h`) e abre direto dizendo `"Você só pode receber se tiver uma autorização..."`.
   - Na `q05` (`Rodada 0 q05 a1 e a3`), como o prazo da pergunta (*"semana passada"*) não permite cravar o dia exato, o modelo abre com `"Depende..."` em vez de `"Sim, desde que..."`.

---

## 3. Ciclos de Ajuste e Verificação (Ciclos 1, 2 e 3)

### Tentativa 1 (única mudança necessária — fechou os Ciclos 1, 2 e 3 de primeira)

- **Mudança aplicada (diff contra a `v1`):** acréscimo da **Regra 6** (`a`, `b`, `c`, `d`) ao final de `REGRAS_DO_MANUAL` v1, 100% geral e **sem citar nenhum produto, número, código, prazo ou situação das perguntas de treino** (zero dígitos além do `6.`):

```diff
@@ -5,2 +5,7 @@
 5. Se a nota [rag] diz ERRO, esta regra vale no lugar da 4: NAO diga que o manual nao cobre; diga que a consulta ao manual falhou agora e que o usuario confirme com o encarregado. Nao invente o procedimento.
+6. Em perguntas de decisao (sim/nao, pode/nao pode, aceita/recusa) ou que envolvam limite, faixa, prazo ou horario:
+   a) Compare o valor, tempo ou horario da pergunta com o limite da regra padrao do manual antes de concluir. Em valores negativos (com sinal de menos, como temperaturas negativas), atencao ao sinal: quanto menor o numero sem o sinal, MAIOR (mais quente) e o valor real, portanto ele esta ACIMA de um limite mais negativo ("ate", "no maximo" ou "ou menos" exige valor igual ou mais negativo/mais frio).
+   b) Converta expressoes de tempo relativas da pergunta para a mesma unidade do prazo ou horario do manual. Se o tempo decorrido ou o horario ja passou do limite da regra padrao, a conclusao e "Não". Se a expressao de tempo for imprecisa e puder cair dentro ou fora do prazo (mas as demais condicoes forem atendidas), comece com "Sim, desde que..." informando o prazo exato do manual (nunca comece com "Depende").
+   c) Quando a pergunta for de sim/nao e os trechos responderem (fora dos casos das regras 4 e 5), comece a resposta pela palavra "Sim" ou "Não" aplicada ao caso concreto segundo a regra padrao, explicitando logo na primeira frase a comparacao entre o dado da pergunta e o limite do manual. Se o caso violar o limite ou horario padrao, comece obrigatoriamente com "Não", mesmo que o manual preveja excecao ou autorizacao especial (explique a excecao e o formulario exigido somente depois da negativa).
+   d) Inclua na resposta todos os limites numericos, prazos e codigos de formulario ou registro do procedimento aplicavel presentes nos trechos, mantendo o papel exato de quem executa cada acao segundo o manual e sem fazer contas de subtracao nao pedidas.
```

---

### Ciclo 1 — Tentativa 1 (`q02` e `q04`)

- **Texto das regras:** `v1 + Regra 6` (`docs/exploracao/regras-proposta.txt`).
- **Resultados:**
  - **`q02`: 3/3 PASSA**
    - *Amostra 1 (`e92db603`):* `"Não, você não deve aceitar, pois −10 °C está acima (mais quente) do limite máximo permitido para congelados, que é de **−12 °C** (aceitar até **−12 °C** e recusar acima de **−12 °C**) (POP-01, seção "4. Temperatura na chegada")."` + cita `F-07`. -> **JUIZ (`a5b376c8`):** `PASSA — Conclusão correta ("Não", recusar), fatos-chave presentes (-12 °C e F-07) e informações fiéis aos trechos fornecidos.`
    - *Amostra 2 (`8b267f6e`):* `"Não, você não deve aceitar (o lote deve ser recusado), pois a temperatura de **−10 °C** está acima (é mais quente) do limite máximo de **−12 °C** exigido para o recebimento de produtos congelados (POP-01, seção "4. Temperatura na chegada")."` + cita `F-07`. -> **JUIZ (`a5b376c8`):** `PASSA — Conclusão correta ("Não", recusar), fatos-chave presentes (-12 °C e F-07) e sem informações inventadas fora dos trechos.`
    - *Amostra 3 (`aa7168ff`):* `"Não, você não deve aceitar (deve recusar), pois a temperatura de **−10 °C** está acima (mais quente) do limite de **−12 °C** estabelecido para o recebimento de produtos congelados (POP-01, seção "4. Temperatura na chegada")."` + cita `F-07`. -> **JUIZ (`a5b376c8`):** `PASSA — Conclusão correta ("Não", recusar), fatos-chave presentes (-12 °C e F-07) e estritamente baseada no trecho de recebimento.`
  - **`q04`: 3/3 PASSA**
    - *Amostra 1 (`eb57c313`):* `"Não, pela regra padrão você não pode trocar, pois a compra foi feita anteontem (há cerca de 48 horas / 2 dias), o que ultrapassa o prazo limite de **24 horas** a partir do horário impresso no cupom estabelecido para produtos perecíveis, como laticínios e frios (POP-03, seção "3. Prazo de troca — produtos perecíveis")."` -> **JUIZ (`770e889b`):** `PASSA — Inicia com "Não", conclui corretamente que não pode trocar pela regra padrão por ultrapassar o prazo de 24 horas, inclui o fato-chave e não inventa informações.`
    - *Amostra 2 (`c67589b2`):* `"Não, pela regra padrão você não pode realizar a troca, pois uma compra feita anteontem (há cerca de 48 horas, ou seja, 2 dias) já ultrapassou o prazo limite de **24 horas** a partir do horário impresso no cupom estabelecido para produtos perecíveis, como laticínios e frios (POP-03, seção "3. Prazo de troca — produtos perecíveis")."` -> **JUIZ (`770e889b`):** `PASSA — Inicia com "Não", conclui corretamente pela impossibilidade de troca no prazo padrão de 24 horas, apresenta o fato-chave obrigatório e atém-se fielmente aos trechos.`
    - *Amostra 3 (`7b114bf6`):* `"Não, você não pode realizar a troca pela regra padrão, pois a compra foi feita anteontem (há cerca de 48 horas / 2 dias), o que ultrapassa o prazo limite de **24 horas** a partir do horário impresso no cupom exigido para produtos perecíveis, como laticínios e frios (POP-03, seção "3. Prazo de troca — produtos perecíveis")."` -> **JUIZ (`770e889b`):** `PASSA — Inicia com "Não", aplica corretamente a regra de 24 horas para perecíveis ao caso de compra feita anteontem, traz o fato-chave e não extrapola os trechos fornecidos.`
- **Falhas no Ciclo 1 — Tentativa 1:** Nenhuma (`6/6 PASSA`). **Ciclo 1 fechado na Tentativa 1.**

---

### Ciclo 2 — Tentativa 1 (`q02`, `q04` + `q10`, `q01`)

- **Texto das regras:** **Exatamente o mesmo texto do Ciclo 1 — Tentativa 1** (`v1 + Regra 6`, diff vazio contra a tentativa anterior). Todas as 4 perguntas foram rodadas novamente do zero (12 novas instâncias de `agente_rag`).
- **Resultados:**
  - **`q02`: 3/3 PASSA** (`799ced26`, `b5a25cb8`, `daedb370` — julgadas por `Juiz C2T1 q02` `d61685a1`: 3/3 `PASSA`).
  - **`q04`: 3/3 PASSA** (`89a134fe`, `b0957a61`, `b52741e5` — julgadas por `Juiz C2T1 q04` `0ca861d6`: 3/3 `PASSA`).
  - **`q10`: 3/3 PASSA**
    - *Amostra 1 (`2cc3919d`):* `"Não, você não terá problema, pois a falta de R$ 3,00 está dentro do limite de tolerância de **até R$ 5,00 (para mais ou para menos)** previsto para o fechamento (POP-04, seção "6. Diferença de caixa")."` + `Formulário F-02`. -> **JUIZ (`c2adf610`):** `PASSA`
    - *Amostra 2 (`fbbfb944`):* `"Não, você não terá problema, pois a diferença de R$ 3,00 para menos está dentro do limite de tolerância de **até R$ 5,00 (para mais ou para menos)** no fechamento do caixa (POP-04, seção "6. Diferença de caixa")."` + `Formulário F-02`. -> **JUIZ (`c2adf610`):** `PASSA`
    - *Amostra 3 (`12f3ab6e`):* `"Não, você não terá problema, pois a diferença de R$ 3,00 para menos está dentro do limite de tolerância de **até R$ 5,00 (para mais ou para menos)** no fechamento (POP-04, seção "6. Diferença de caixa")."` + `Formulário F-02`. -> **JUIZ (`c2adf610`):** `PASSA`
  - **`q01`: 3/3 PASSA** (corrigiu a falha 2/3 da Rodada 0!)
    - *Amostra 1 (`56330e61`):* `"Não, você não pode receber o caminhão pelo procedimento padrão, pois o horário de chegada (**15h**) está fora do limite de horário de funcionamento da doca, que vai das **6h às 14h** de segunda a sábado..."` + exceção `Formulário F-03`. -> **JUIZ (`932a6535`):** `PASSA`
    - *Amostra 2 (`a19e9656`):* `"Não, pela regra padrão você não pode receber o caminhão às **15h**, pois esse horário ultrapassa o limite permitido para entregas de fornecedores, que é das **6h às 14h** de segunda a sábado..."` + exceção `Formulário F-03`. -> **JUIZ (`932a6535`):** `PASSA`
    - *Amostra 3 (`950495f7`):* `"Não, pois o horário de chegada às 15h ultrapassa o limite do horário padrão de recebimento na doca, que é das **6h às 14h** de segunda a sábado..."` + exceção `Formulário F-03`. -> **JUIZ (`932a6535`):** `PASSA`
- **Falhas no Ciclo 2 — Tentativa 1:** Nenhuma (`12/12 PASSA`). **Ciclo 2 fechado na Tentativa 1.**

---

### Ciclo 3 — Tentativa 1 (`q02`, `q04`, `q10`, `q01` + `q05`, `q09`)

- **Texto das regras:** **Exatamente o mesmo texto dos Ciclos 1 e 2** (`v1 + Regra 6`, diff vazio contra a tentativa anterior). Todas as 6 perguntas foram rodadas novamente do zero (18 novas instâncias de `agente_rag`).
- **Resultados:**
  - **`q02`: 3/3 PASSA** (`ff27e1b8`, `77d466e1`, `33d44aab` — julgadas por `Juiz C3T1 q02` `47b012ed`: 3/3 `PASSA`).
  - **`q04`: 3/3 PASSA** (`f7c555ea`, `f7e60de2`, `373c1ca5` — julgadas por `Juiz C3T1 q04` `5e785528`: 3/3 `PASSA`).
  - **`q10`: 3/3 PASSA** (`acf10a58`, `395e2381`, `56483739` — julgadas por `Juiz C3T1 q10` `19616312`: 3/3 `PASSA`).
  - **`q01`: 3/3 PASSA** (`70e22a6d`, `0c98dd01`, `8e88f60f` — julgadas por `Juiz C3T1 q01` `9130f504`: 3/3 `PASSA`).
  - **`q05`: 3/3 PASSA** (corrigiu a falha 1/3 da Rodada 0!)
    - *Amostra 1 (`297028fc`):* `"Sim, desde que a compra feita na semana passada tenha ocorrido há no máximo **7 dias corridos**, que é o prazo limite para troca por arrependimento de produtos não perecíveis (como itens de higiene) em perfeito estado e lacrados (POP-03, seção "4. Prazo de troca — produtos não perecíveis")."` -> **JUIZ (`20e2206a`):** `PASSA`
    - *Amostra 2 (`3057d623`):* `"Sim, desde que a compra feita na semana passada ainda esteja dentro do limite máximo de **7 dias corridos** após a compra e o shampoo esteja em perfeito estado e lacrado..."` -> **JUIZ (`20e2206a`):** `PASSA`
    - *Amostra 3 (`a5ce627b`):* `"Sim, desde que a compra feita na "semana passada" tenha ocorrido há no máximo **7 dias corridos**, pois o manual permite a troca por **arrependimento** em até **7 dias corridos** após a compra..."` -> **JUIZ (`20e2206a`):** `PASSA`
  - **`q09`: 3/3 PASSA**
    - *Amostra 1 (`d154f9c1`):* `"Como a sua gaveta está com quase **R$ 900,00**, esse valor já ultrapassou o limite de **R$ 800,00 em dinheiro**. Quando a gaveta passa de **R$ 800,00 em dinheiro**, o PDV bloqueia novas vendas em dinheiro até que o procedimento de **sangria** seja feito... Acione o **fiscal de caixa**..."` -> **JUIZ (`6982e152`):** `PASSA`
    - *Amostra 2 (`0572f261`):* `"Como a sua gaveta está com quase R$ 900,00 em dinheiro — valor acima do limite de **R$ 800,00 em dinheiro** —, deve ser realizada a **sangria**... O **fiscal de caixa** recolhe o valor excedente da gaveta, deixando apenas o **fundo de troco**..."` -> **JUIZ (`6982e152`):** `PASSA`
    - *Amostra 3 (`69204b76`):* `"Como a sua gaveta está com quase R$ 900,00 em dinheiro, esse valor já ultrapassou o limite de **R$ 800,00 em dinheiro**, situação em que o PDV bloqueia novas vendas em dinheiro até que seja feita a **sangria**... O **fiscal de caixa** deve recolher o valor excedente..."` -> **JUIZ (`6982e152`):** `PASSA`
- **Falhas no Ciclo 3 — Tentativa 1:** Nenhuma (`18/18 PASSA`). **Ciclo 3 fechado na Tentativa 1.**

### Resumo Consolidado dos Ciclos (com o mesmo texto `v1 + Regra 6`)

| Pergunta | Rodada 0 (`v1`) | Ciclo 1 (`v1 + Regra 6`) | Ciclo 2 (`v1 + Regra 6`) | Ciclo 3 (`v1 + Regra 6`) | Acumulado com `v1 + Regra 6` |
|---|---|---|---|---|---|
| **q02** | 3/3 | **3/3** | **3/3** | **3/3** | **9/9 (100%)** |
| **q04** | 3/3* | **3/3** | **3/3** | **3/3** | **9/9 (100%)** |
| **q10** | 3/3 | — | **3/3** | **3/3** | **6/6 (100%)** |
| **q01** | **2/3 (FALHOU)** | — | **3/3** | **3/3** | **6/6 (100%)** |
| **q05** | **1/3 (FALHOU)** | — | — | **3/3** | **3/3 (100%)** |
| **q09** | 3/3 | — | — | **3/3** | **3/3 (100%)** |
| **Total** | **15/18 (4/6 perguntas)** | **6/6 (2/2)** | **12/12 (4/4)** | **18/18 (6/6)** | **36/36 (100%)** |

*\*Na Rodada 0, a `q04` acertou a conclusão negativa nas 3 amostras, mas todas começaram por `"Em regra, não..."` em vez de `"Não"`. Com a Regra 6, 9 de 9 amostras da `q04` começaram pela palavra `"Não"`.*

---

## 4. Autocrítica da Proposta

1. **Verificação Anti-Decoreba:**
   A Regra 6 proposta **não cita nenhum produto, número, código, prazo ou situação** das 6 perguntas de treino. Não há um único algarismo no texto da Regra 6 além do próprio índice `"6."` (nem mesmo o número zero é citado: a comparação negativa foi formulada pela relação geral entre o número sem o sinal de menos e a grandeza real).
2. **Em que tipo de pergunta a proposta pode piorar?**
   - **Verbosidade / excesso de detalhes do mesmo trecho (efeito colateral da Regra 6d):** A alínea `d)` (*"Inclua na resposta todos os limites numericos, prazos e codigos de formulario ou registro do procedimento aplicavel presentes nos trechos"*) garante que nenhum fato-chave da métrica `(b)` seja omitido (como o `F-07` na `q02` ou os `10 ml` na `q11`), porém faz o modelo listar também as outras linhas de uma mesma tabela do trecho aplicável (ex.: na `q02`, além do limite de congelados, o modelo listou como referência os limites de resfriados, laticínios e frios que estão na mesma tabela do `POP-01 §4`; na `q10`, além da faixa até R$ 5,00, listou as faixas de R$ 5,01 a R$ 50,00 e acima de R$ 50,00 do `POP-04 §6`). Isso **não** prejudica a métrica `(d) fidelidade estrita` nem `(f) correção` (pois todos esses dados vêm literalmente dos trechos recuperados e a regra 4 do juiz de correção diz que *"trazer informação a mais que não contradiz o gabarito NÃO torna a resposta incorreta"*), mas torna a resposta mais longa e menos enxuta para leitura em WhatsApp.
   - **Perguntas alternativas (`q07`: *"isso é caso de F-07 ou recebo assim mesmo?"*) ou compostas (`q16`: *"qual a diferença da etiqueta amarela pra vermelha? a amarela qualquer repositor pode colar?"*):** A alínea `c)` restringe o início por `"Sim"` ou `"Não"` a *"Quando a pergunta for de sim/nao"*, mas um LLM pode interpretar a segunda metade da `q16` ou a alternativa da `q07` como pergunta de sim/não e começar a resposta inteira por `"Não"`. Na `q07` começar por `"Não recebe"` é compatível com o gabarito, mas na `q16` a primeira pergunta é aberta (*"qual a diferença..."*) e começar por `"Não"` ficaria artificial se o modelo responder a segunda pergunta antes da primeira.
   - **Perguntas `sem_resposta` com quase-acerto (`q19` e `q20`):** A alínea `c)` inclui a trava explícita `"(fora dos casos das regras 4 e 5)"` para evitar que o modelo comece `q19` ou `q20` com `"Não"`. Ainda assim, no modelo de produção (`deepseek/deepseek-chat`), existe o risco de a ênfase em começar por `"Sim"` ou `"Não"` competir com a Regra 4 (`"O manual de procedimentos não cobre isso."`) caso o modelo confunda "o manual não prevê demissão" com "Não, o operador não é demitido".

---

## 5. Limites Honestos (Gemini vs. Modelo de Produção `deepseek/deepseek-chat`)

1. **Raciocínio interno (`thinking`) vs. geração puramente autorregressiva (`reasoning_tokens: 0`):**
   Os subagentes do Antigravity rodaram com Gemini 4 Argon (High), que executa uma cadeia de pensamento interna (`thinking`) antes de emitir o primeiro token visível. Já o modelo de produção do `synthesize_final` (`deepseek/deepseek-chat` via OpenRouter) roda com `reasoning_tokens: 0` (conforme registrado nos JSONs de `m9` e `m10`). Por isso, na Rodada 0 com `v1`, o Gemini acertou 3/3 na `q02` (`-10 °C` vs. `-12 °C`) mesmo sem a Regra 6, enquanto o `deepseek/deepseek-chat` errou 2 de 6 na `v1` e 2 de 2 na `v2`.
2. **Por que a Regra 6 foi desenhada pensando no `deepseek/deepseek-chat` (e não só no Gemini):**
   - A alínea `6a` traduz a comparação de números negativos para uma regra mecânica diretamente sobre a superfície do token (*"quanto menor o numero sem o sinal, MAIOR (mais quente) e o valor real, portanto ele esta ACIMA de um limite mais negativo"*), evitando que o `deepseek-chat` aplique a heurística de números positivos ao ler `"Aceitar até −12 °C"`.
   - A alínea `6c` manda explicitar logo na primeira frase a comparação entre o dado da pergunta e o limite do manual, mas **só um teste pago com `deepseek/deepseek-chat`** dirá se colocar `"Sim"` ou `"Não"` na 1ª palavra (com as alíneas `6a` e `6b` no system prompt) já elimina o erro da `q02` no DeepSeek ou se o DeepSeek ainda precisa enunciar o limite antes da palavra `"Sim"`/`"Não"`.
3. **Intervenção controlada na `q10` durante a exploração:**
   Nesta exploração sem API, o trecho `POP-04 §6` foi incluído no contexto da `q10` para testar a comparação de limite (`R$ 3` vs. `até R$ 5`). No pipeline real de ponta a ponta (`avaliar_respostas.py`), enquanto a busca híbrida top-5 não recuperar o `POP-04 §6` para a `q10`, a `q10` continuará limitada pela **busca** (recall@5 = 16/17), independentemente do prompt do `synthesize_final`.

---

## 6. Proposta de Pré-Registro para o Teste de Verdade (Prova Final Lacrada + Gabarito)

> **Apenas texto do critério proposto para `docs/RAG.md` — nada foi executado.**

```markdown
## Missão 11 — Regra de decisão para limites, prazos e Sim/Não (pré-registro, ANTES da medição)

Registrado antes de qualquer execução paga da Missão 11.
Hipótese (da exploração com subagentes em `docs/exploracao/subagentes-q02.md`):
acrescentar à `v1` a Regra 6 (comparação explícita de limites e sinais
negativos, conversão de expressões de tempo relativas, veredito Sim/Não pela
regra padrão antes de exceções e inclusão de limites/códigos do trecho) elimina
as inversões de Sim/Não em limites e temperaturas negativas sem derrubar
fatos-chave, correção ou fidelidade.

**Uma variável: o texto das regras do manual no `synthesize_final` (`v4` = `v1` + Regra 6 de `docs/exploracao/regras-proposta.txt`).**
Continuam iguais à Missão 8/9: busca híbrida `top_k = 5` sem rerank, índice e
`indice_meta` da Missão 8, supervisor, modelo de produção
(`deepseek/deepseek-chat`), juiz v1 com `--sem-calibracao` e `alvo = resposta_final`,
e `fatos_chave_v1.yaml`. Sem etapa 2 de formatação.

### Desenho (2 blocos medidos, ordem intercalada)

1. **Bloco A — Gabarito (`gabarito.yaml`, 20 perguntas, N = 2 rodadas por versão):**
   - Ordem intercalada: `v1-r1`, `v4-r1`, `v1-r2`, `v4-r2` (pelo grafo completo).
2. **Bloco B — Prova final lacrada (`prova10-v1.yaml`, 10 perguntas de Sim/Não com número, limite ou prazo, sha256 `819c0eb716736837c9d78e179aa8058869c48db89cd55879a9b1df5fece6b33f`, N = 2 rodadas por versão):**
   - Conferir o `sha256` de `prova10-v1.yaml` em código antes de iniciar; se divergir, abortar.
   - Ordem intercalada: `prova10-v1-r1`, `prova10-v4-r1`, `prova10-v1-r2`, `prova10-v4-r2`.
   - Rodada uma única vez, sem ajuste posterior.

### Regra de decisão (vinculante; `v4` só vira padrão se TODAS passarem)

1. **a) Prova lacrada (`prova10-v1.yaml`, 10 perguntas × 2 rodadas = 20 respostas por versão):**
   - **a.1) Ganho ou teto na conclusão Sim/Não:** a média de acertos de conclusão Sim/Não da `v4` nas 10 perguntas da `prova10-v1` deve ser **≥ 9,0 / 10** (isto é, ≥ 18/20 nas 2 rodadas somadas) **E** maior ou igual à média da `v1`.
   - **a.2) Temperaturas negativas na prova lacrada:** nas 5 perguntas de temperatura negativa da `prova10-v1` (10 respostas nas 2 rodadas da `v4`), **zero** erros de conclusão Sim/Não (10/10).
2. **b) Sim/Não no gabarito (`q01, q02, q04, q05, q10`):**
   - Nas perguntas de Sim/Não do gabarito cujo trecho-fonte foi recuperado pela busca (`q01, q02, q04, q05`), **zero** contradições de Sim/Não na 1ª palavra nas 2 rodadas da `v4` (8/8), e `q02` deve concluir pela recusa nas 2 rodadas (2/2).
3. **c) Sem queda no gabarito (20 perguntas, média das 2 rodadas):**
   - Para cada uma das métricas `(b) fatos-chave` (n = 17), `(f) correção` (n = 17), `(d) sem afirmação grave` (n = 20), `(d) fidelidade estrita` (n = 20) e `(c) citação espontânea` (n = 17):
     `média_v1 − média_v4 ≤ 1,0` (queda de 1,0 passa; de 1,5 reprova).
```
