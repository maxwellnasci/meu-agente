# POP-01 — Recebimento de Mercadorias

> Supermercado Bom Preço (empresa fictícia, dados inventados para teste de RAG).
> Versão 3.2 — vigente desde 01/03/2026. Responsável: Gerência de Logística.

## 1. Objetivo

Padronizar a conferência de cargas na doca para que nenhuma mercadoria entre
no estoque sem nota fiscal conferida, temperatura registrada e validade
mínima garantida.

## 2. Horário da doca

- Fornecedores entregam de segunda a sábado, das **6h às 14h**.
- Domingo e feriado só recebem **hortifrúti e pães**, das 6h às 10h.
- Entregas fora do horário precisam de autorização por escrito do gerente de
  loja, registrada no **Formulário F-03 (Recebimento Extraordinário)**.
- Cada caminhão tem no máximo **40 minutos** de doca. Passou disso, o próximo
  da fila entra e o atrasado volta para o fim da fila.

## 3. Conferência da nota fiscal

1. O conferente compara a nota fiscal com o pedido de compra no sistema.
2. Divergência de quantidade de até **2%** do item é aceita e anotada no
   verso do canhoto.
3. Divergência acima de 2%, produto trocado ou preço diferente do pedido:
   a carga do item é **recusada** e o conferente preenche o
   **Formulário F-07 (Divergência de Recebimento)**.
4. O canhoto só é assinado depois da conferência física completa.

## 4. Temperatura na chegada

Medir com o termômetro tipo espeto em **3 volumes por lote** (início, meio e
fim do caminhão) e anotar no F-07 mesmo quando estiver tudo certo.

| Categoria            | Aceitar até | Recusar acima de |
|----------------------|-------------|------------------|
| Congelados           | −12 °C      | −12 °C           |
| Resfriados (carnes)  | 7 °C        | 7 °C             |
| Laticínios           | 10 °C       | 10 °C            |
| Frios fatiados       | 8 °C        | 8 °C             |
| Hortifrúti           | sem limite  | — (só avaliação visual) |

Congelado com sinal de descongelamento (gelo acumulado, embalagem molhada ou
produto amolecido) é recusado **mesmo que o termômetro marque −12 °C ou
menos**.

## 5. Validade mínima na entrada

- Perecíveis precisam chegar com pelo menos **70%** da vida útil restante.
  Exemplo: iogurte com validade total de 30 dias precisa ter no mínimo 21
  dias pela frente.
- Não perecíveis (mercearia seca, limpeza, higiene) precisam ter pelo menos
  **6 meses** de validade restante.
- Abaixo desses limites, recusar o item e registrar no F-07.

## 6. Avarias na doca

- Caixa amassada sem dano ao produto: aceitar e separar para venda normal.
- Embalagem primária violada, lata estufada ou vazamento: recusar e
  fotografar. As fotos vão anexadas ao F-07 no sistema em até **24 horas**.
- Avaria descoberta **depois** de assinado o canhoto não é mais recusa: vira
  quebra interna, lançada com o código **Q-14 (Avaria pós-recebimento)**.

## 7. Prazo para guardar

Depois da conferência, o tempo máximo entre a doca e a câmara é de
**30 minutos** para congelados e resfriados e de **2 horas** para mercearia
seca.
