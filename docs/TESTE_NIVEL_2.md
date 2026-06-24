# Teste de Capacidades - Nível 2 (Sub-agentes)

## Data
2026-06-24

## Objetivo
Validar que a correção do auth (paste-api-key feita hoje cedo)
funcionou e o Amigão consegue criar sub-agentes em paralelo sem
erro "missing-provider-auth".

## Tarefa enviada
"Amigão, preciso que você faça uma tarefa multi-step:
1. Crie um sub-agente para listar arquivos em /tmp
2. Crie OUTRO sub-agente para verificar a data do sistema
3. Reúna os 2 resultados em um relatório consolidado
Use sessions_spawn explicitamente."

## Resultados

### Sub-agente 1: listar_tmp
- Ferramenta: sessions_spawn + sessions_history (interno: exec)
- Comando executado: ls -la /tmp
- Resultado: diretório vazio (apenas . e ..)
- Status: ✅ Sucesso

### Sub-agente 2: verificar_data
- Ferramenta: sessions_spawn + sessions_history (interno: exec)
- Comando executado: date -u
- Resultado: Wed Jun 24 20:41:18 UTC 2026
- Status: ✅ Sucesso

### Orquestração
- Paralelismo: REAL (2 spawns simultâneos, não sequencial)
- Aguardamento: sessions_yield (libera thread principal)
- Consolidação: sessions_history para coletar resultados
- Status: ✅ Funcionou conforme arquitetura esperada

## DESCOBERTAS TÉCNICAS (análise de bastidores)

### Descoberta 1: Auth corrigido validado em produção
ZERO erros de missing-provider-auth em todos os runs. A correção
do paste-api-key feita hoje cedo está funcionando como esperado.
stopReason=stop em ambos sub-agentes (saída limpa).

### Descoberta 2: Sub-agentes COMPARTILHAM sandbox
Sub-agentes do MESMO agente principal NÃO criam novos containers
Docker. Eles rodam DENTRO do mesmo container sandbox existente
(openclaw-sbx-agent-main-XXXX) via docker exec interno.

Implicações:
- ✅ Eficiência: zero overhead de containers extras
- ✅ Isolamento entre sessões/clientes: mantido perfeitamente
- ⚠️ Sub-agentes da MESMA sessão se conhecem (compartilham contexto)

### Descoberta 3: Tool policy hierárquica (anti-explosão recursiva)
O OpenClaw aplica automaticamente:
- Agente principal: pode criar sub-agentes ✅
- Sub-agentes: NÃO podem criar sub-sub-agentes ❌ (subagents.deny)

Isso PREVINE explosão recursiva (DoS por sub-agentes criando
infinitos sub-agentes). Camada extra de defense in depth.

## Arquitetura confirmada

```
Sessão Cliente X (sandbox próprio - openclaw-sbx-agent-main-X)
├── Amigão (agente principal)
│   ├── pode usar: exec
│   └── pode criar: sub-agentes
├── Sub-agente A (compartilha sandbox de X)
│   ├── pode usar: exec
│   └── NÃO pode criar: mais sub-agentes
└── Sub-agente B (compartilha sandbox de X)
    └── (mesmas regras)

Sessão Cliente Y (sandbox SEPARADO)
└── (isolamento total entre X e Y)
```

## Implicação para o projeto MXOS

### Modelo de sessão por cliente
Cada cliente = sandbox isolado próprio. PERFEITO para multi-tenant.

### Sub-agentes para tarefas paralelas
Excelente para casos como:
- Buscar info em paralelo (1 agente por canal)
- Validar múltiplas regras simultaneamente
- Coordenar checkpoints (1 agente por etapa)

### Limite anti-explosão
A proteção subagents.deny no segundo nível protege contra:
- Bugs no código que poderiam criar loops infinitos
- Comportamento adversário do LLM principal
- Bem para arquitetura defensiva

### Atenção privacidade
Sub-agentes da mesma sessão compartilham contexto. Para tarefas
SENSÍVEIS, talvez usar sessões separadas em vez de sub-agentes
internos.

## Veredito do Nível 2
✅ APROVADO COM LOUVOR
✅ Correção do auth validada em produção
✅ Paralelismo real funciona
✅ Arquitetura de isolamento por sessão confirmada
✅ Descoberta extra: proteção anti-explosão recursiva
✅ Pronto para Nível 3 (cenário MXOS-like)

## Próximo passo
docs/TESTE_NIVEL_3.md - Cenário MXOS-like (caso de uso real
para clínicas, oficinas, etc.)
