# POP-02 — Controle de Validade e Perecíveis

> Supermercado Bom Preço (empresa fictícia, dados inventados para teste de RAG).
> Versão 2.0 — vigente desde 15/01/2026. Responsável: Gerência de Perecíveis.

## 1. Objetivo

Garantir que nenhum produto vencido fique exposto e reduzir a perda por
validade com rebaixa de preço planejada.

## 2. Ronda diária de validade

- Toda loja faz a ronda de validade **duas vezes por dia**: às **7h30**
  (antes da abertura) e às **15h**.
- A ronda da manhã cobre o setor inteiro de perecíveis; a da tarde cobre só
  laticínios, frios e padaria.
- O repositor anota cada item encontrado no **Formulário F-12 (Controle de
  Validade)**, com código de barras, lote, data de validade e quantidade.
- O F-12 preenchido é entregue ao encarregado de perecíveis até as **9h**
  (ronda da manhã) e até as **16h** (ronda da tarde).

## 3. Rebaixa de preço por proximidade do vencimento

A rebaixa só pode ser aplicada pelo encarregado de perecíveis, com a etiqueta
amarela "Oferta do Dia".

| Dias até vencer | Laticínios e frios | Padaria | Carnes resfriadas |
|-----------------|--------------------|---------|-------------------|
| 5 dias          | 20% de desconto    | —       | —                 |
| 3 dias          | 30%                | —       | 25%               |
| 2 dias          | 40%                | —       | 40%               |
| 1 dia           | 50%                | 50%     | 50%               |
| Dia do vencimento | retirar da área de venda | retirar | retirar |

Pão francês e produtos de padaria feitos na loja **não** entram na tabela de
dias: o que sobra no fim do dia vai para a doação (ver seção 6).

## 4. Retirada de vencidos

1. Produto no dia do vencimento sai da gôndola até as **8h**, antes da
   abertura da loja.
2. O item vencido é lançado como quebra com o código **Q-22 (Vencimento)**.
3. O lançamento é feito no mesmo dia; quebra sem lançamento é tratada como
   furto desconhecido no inventário.

## 5. Regra PVPS na reposição

A reposição segue **PVPS — Primeiro que Vence, Primeiro que Sai**: o produto
com validade mais curta fica na frente da gôndola e o recém-chegado vai atrás.
Não confundir com PEPS (data de entrada): no Bom Preço vale sempre a data de
validade.

## 6. Doação de excedentes

- Produtos de padaria do dia e hortifrúti com aparência imperfeita (mas
  próprios para consumo) são doados ao banco de alimentos parceiro.
- A coleta acontece **terças e sextas às 18h**.
- Nunca doar produto vencido ou com embalagem violada.
- Cada doação é registrada no **Formulário F-15 (Termo de Doação)**, assinado
  pelo gerente de loja.

## 7. Cliente encontrou produto vencido na gôndola

- O operador ou fiscal troca o produto na hora por um igual dentro da
  validade, **sem exigir nota fiscal**, se o cliente ainda não pagou.
- Se o cliente já comprou e voltou depois, seguir o POP-03 (Troca e
  Devolução), seção "Produto vencido vendido pela loja".
- O fiscal abre um registro de não conformidade e avisa o encarregado de
  perecíveis no mesmo turno.
