# Protocolo Multi-IA do Projeto MEU AGENTE

## Modelos usados e seus papéis

### Antigravity Sonnet (Sonnet 4.6 think)
- Papel: AUDITOR / ANALISTA
- Usar quando: decisões de segurança, validação crítica, dúvidas, mudanças arquiteturais, COMPROVAR campos de config antes de aplicar
- Custo: usa bônus semanal do plano (recurso limitado)
- Princípio: "cirurgião - cortes precisos onde importa"

### Antigravity Gemini (Gemini 3.1-pro / 3.5-pro quando disponível)
- Papel: EXECUTOR
- Usar quando: tarefa já decidida (já validada pelo Sonnet ou por documentação), passos mecânicos, edição de arquivos, commits, deploys
- Custo: ilimitado no plano Google Pro
- Princípio: "operador eficiente para tarefas definidas"

### Claude Code (terminal)
- Papel: AUDITOR LOCAL com acesso real aos arquivos
- Usar quando: precisa investigar arquivos no disco, validações finais antes de mudanças

### Claude (chat - parceiro de planejamento)
- Papel: ORQUESTRADOR / PARCEIRO DE ESTRATÉGIA  
- Usar quando: planejamento, revisão de planos, decisões estratégicas, brainstorm
- Comunica usando os termos "Antigravity Sonnet" e "Antigravity Gemini" para indicar qual modelo usar em qual tarefa

## Regra de Ouro
"Sem prova, sem aprovação" - especialmente para configurações de segurança. Toda config crítica deve ser validada com documentação oficial ou schema do próprio sistema antes de aplicar.

## Padrão de Fluxo Ideal
1. Claude (chat) → orquestra e revisa plano
2. Antigravity Sonnet → analisa e prova com docs oficiais
3. Aprovação do usuário (Max) → baseada em prova
4. Antigravity Gemini → executa a tarefa validada
5. Claude Code (terminal) → auditoria final se necessário

## Lições aprendidas
- Sessão 2026-06-23: Sonnet auditando trabalho de modelo mais econômico pegou 2 campos inventados (nodes.enabled, browser.enabled) que quebrariam o gateway.
- Sessão 2026-06-24: Mesmo fluxo (Sonnet valida + Gemini executa) resolveu warnings do gateway sem retrabalho.
