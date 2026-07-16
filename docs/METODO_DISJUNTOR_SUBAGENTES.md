# Método de Resolução de Problemas: Disjuntor + Subagentes Investigativos

Este documento detalha o método utilizado para diagnosticar e resolver o "Bug 4" (travamento da execução por tempo indefinido em certas ferramentas), combinando a estratégia do **Disjuntor (Circuit-Breaker)** com **Subagentes Investigativos Paralelos**.

## 1. O Problema (O que estávamos enfrentando)
- O agente congelava aleatoriamente ("hang") durante a execução de chamadas longas, como o uso do `github_repo_report`.
- Em vez de estourar um timeout seguro, a thread ficava presa indefinidamente.

## 2. A Estratégia do Disjuntor ("Circuit-Breaker")
A estratégia do disjuntor envolve isolar componentes para validar se eles são a causa raiz do problema.
1. Em um ambiente local, desativamos plugins pesados ou secundários (no nosso caso, definindo `enabled: false` para o `acpx` e `memory-core` no `openclaw.json`).
2. Se o problema desaparece, ligamos novamente (um por um) até que o erro volte a acontecer, identificando com precisão o componente ofensor.

## 3. Investigação Aprofundada com Subagentes Paralelos
Quando não é possível executar o fluxo completo de teste (ex: devido a erros de compilação locais do Node 24), podemos isolar o código e usar **subagentes paralelos**.
1. Identificamos todos os "pontos de contato" do sistema (no nosso caso, os `hooks` do OpenClaw).
2. Distribuímos a análise desses hooks para múltiplos subagentes, rodando simultaneamente em background.
3. **Instruções para os Subagentes**: Cada subagente recebeu um hook específico para:
   - Verificar a definição do timeout padrão desse hook.
   - Identificar quais plugins registravam aquele hook.
   - Analisar o código do handler para identificar chamadas de rede ou subprocessos não protegidos.

## 4. O Diagnóstico Exato (A Descoberta)
Cruzando as análises dos subagentes, descobrimos um ponto de falha cego na arquitetura:
- O plugin `acpx` registrava o hook `reply_dispatch`.
- O hook `reply_dispatch` **não estava listado na tabela de timeouts padrão** (`DEFAULT_MODIFYING_HOOK_TIMEOUT_MS_BY_HOOK` em `hooks.ts`).
- O handler do `acpx` para `reply_dispatch` realizava chamadas de rede (`runTurn` no backend ACP).
- Conclusão: Se essa chamada de rede travasse, o OpenClaw nunca cancelaria o hook, congelando o pipeline inteiro (Bug 4 validado e explicado).

## 5. A Correção
Com base na prova fornecida pelos subagentes:
- Editamos `hooks.ts` para incluir limites de segurança estritos para `reply_dispatch` (30.000 ms) e `reply_payload_sending` (15.000 ms).
- Criamos testes de unidade com timers falsos (fake timers no Vitest) para garantir que um handler travado obrigatoriamente estoure o limite e permita que a execução continue.

## Resumo do Workflow
Quando nos depararmos com intermitências complexas no futuro:
1. Aplique o método do **Disjuntor** para eliminar suspeitos.
2. Invoque **Subagentes Investigativos** (`invoke_subagent`) para varrer e analisar profundamente o código suspeito (ex: hooks, delegates).
3. Provoque a hipótese com **testes isolados unitários**, simulando o problema (ex: fake timers).
4. Aplique a correção na raiz do design (timeout de segurança).
