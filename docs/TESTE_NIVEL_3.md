# Teste de Capacidades - Nível 3 (Cenário MXOS-like - Arbo)

## Data
2026-06-24

## Objetivo
Validar se o Amigão (OpenClaw + DeepSeek V4-pro) consegue
raciocinar como assistente digital de um negócio real (academia
de CrossFit/Hyrox), simulando atendimento de aluno com situação
complexa.

## Cenário enviado
Aluno de 3 meses na Arbo enviou mensagem sobre fisgada no
joelho durante box jump, questionando se deveria treinar e se
perderia a aula caso não fosse.

Foi pedido ao Amigão:
1. Analisar intenção da mensagem
2. Sugerir resposta como assistente
3. Listar ações operacionais
4. Listar informações necessárias do sistema
5. Sugerir o que a Arbo deveria ter cadastrado

## Resposta do Amigão (resumida)
- Análise em 3 camadas (explícita/latente/emocional)
- Resposta empática com orientação clara "não treine"
- 5 ações operacionais propostas
- Lista de 8 informações necessárias do sistema
- Schema de dados + gatilhos + integrações sugeridas

## ANÁLISE QUALITATIVA - PONTOS POSITIVOS

### Raciocínio estratégico genuíno
A análise das 3 camadas demonstra insight contextual real, não
clichê. A leitura "a pergunta não é sobre o joelho, é 'esse
lugar vai me apoiar?'" é raciocínio aplicado a retenção de
aluno novo (< 6 meses = frágil).

### Schema de dados implementável
A estrutura sugerida (Aluno: plano, créditos_reposição,
data_início, histórico_lesões, adaptações_ativas,
termo_assinado) é tecnicamente coerente e implementável.

### Gatilhos automáticos inteligentes
Sugestão de flags por palavras-chave ("dor", "fisgada",
"lesão") + tom diferenciado por tempo de casa demonstra
raciocínio de produto, não de chatbot.

### Tom apropriado e seguro
Postura "não treine hoje" é correta para um assistente
(orienta sem diagnosticar). Encaminhamento para fisioterapeuta
é apropriado.

## ANÁLISE QUALITATIVA - PROBLEMAS CRÍTICOS

Identificados por análise crítica do Sonnet (Claude Code) posterior à resposta.

### PROBLEMA 1: Alucinação funcional — política inventada
A seção 4 da resposta corretamente listou "Política de reposição"
como INFO QUE NÃO TEM. A seção 5.2 da mesma resposta inventou
política específica: "até 2x/mês, com aviso de 2h, válido por 30 dias".

Risco: parece dado real, está errado. Cliente que ler pode
assumir como verdade.

### PROBLEMA 2: Citação fabricada atribuída a pessoa real
Inseriu na resposta ao aluno:
> "O Coach sempre fala: 'um dia de cautela evita 3 semanas parado.'"

O Amigão INVENTOU uma citação e a atribuiu ao Coach da Arbo.
Em produção, Coach lendo isso destruiria credibilidade do
sistema imediatamente.

### PROBLEMA 3: Ação falsa declarada como concluída
Frase usada na resposta ao aluno: "Já alertei o Coach sobre o que você relatou."

O Amigão NÃO alertou ninguém (não tem integração WhatsApp,
não tem acesso à agenda). Mas afirmou ação como CONCLUÍDA.

Risco operacional grave: aluno aparece no box 2h depois achando
que Coach foi avisado, Coach não sabe de nada, Arbo parece
incompetente — exatamente o oposto do que a resposta tenta construir.

Risco legal: promessa operacional falsa pode gerar exposição.

### PROBLEMA 4: Framing ambíguo nas ações
As ações foram listadas como "ações que eu tomaria" mas o Amigão
não pode executar nenhuma agora (cancelar check-in, notificar via
WhatsApp, registrar no banco). Cliente leria como "agente já faz",
quando é apenas sugestão de roadmap.

## INSIGHT TÉCNICO MAIS VALIOSO

Análise do Sonnet:
> "A qualidade textual é do DeepSeek V4-pro, não da arquitetura
> OpenClaw. O diferencial real do OpenClaw aparece quando o
> agente EXECUTA as ações."

Implicação para o MXOS:
- Agente que só ANALISA → API direta de LLM resolve, sem
  precisar de toda a arquitetura sandbox
- Agente que AGE (cancela check-in, notifica Coach via
  WhatsApp, registra no banco) → AÍ a arquitetura OpenClaw
  + sandbox + integrações se justifica

**O moat do MXOS é EXECUÇÃO, não análise textual.**

## VEREDITO

**Nota: 7/10** (análise crítica Sonnet)

Acima da média pelo raciocínio aplicado, schema de dados coerente
e resposta ao aluno bem construída.

Não pode ir para cliente ainda devido aos 3 problemas críticos acima.

## O QUE FALTA PARA "PRONTO PRA CLIENTE"

1. **Implementar camada de Supervisor (LLM as a Judge):**
   - Bloquear citações fabricadas de pessoas reais
   - Bloquear afirmações sobre dados não fornecidos pelo sistema
   - Bloquear declaração de ação concluída sem integração real confirmada

2. **Separar claramente na arquitetura:**
   - O que o agente FAZ AGORA (resposta textual)
   - O que PRECISARIA SER INTEGRADO (ações operacionais futuras)

3. **Implementar integrações reais:**
   - WhatsApp Business API (notificação ao Coach)
   - Banco de dados (Supabase) para política/aluno/histórico
   - Agenda (cancelamento/reposição automático)

## LIÇÕES APRENDIDAS

### Lição 1: Alucinação elegante é mais perigosa que erro óbvio
Resposta com tabelas, emojis e estrutura bonita engana o
leitor. Erros óbvios você vê; erros bem formatados você
aprova sem perceber.

### Lição 2: Protocolo de análise crítica tem valor real
Avaliação inicial (impressionista) teria dado aprovação.
Análise crítica sistemática pegou 3 problemas graves.
Diferença: protocolo de não-confiar-na-primeira-impressão.

### Lição 3: O diferencial do MXOS é AÇÃO, não análise
Texto bonito qualquer LLM faz. Integrar com sistemas reais
do cliente é o que vai justificar o preço.

### Lição 4: Pessoas reais não podem ser personagens
Agente NUNCA pode atribuir frase ou ação a pessoa real do
contexto do cliente (Coach, médico, dono, etc.).

## PRÓXIMOS PASSOS

- Planejar integrações reais (n8n + WhatsApp Business + Supabase)
- Criar skill com políticas reais da Arbo (`references/politicas-arbo.md`)
- Testar reusabilidade do AGENTS.md Parte A em outros clientes

---

## ⚠️ UPDATE 2026-06-24 — FALHAS CRÍTICAS RESOLVIDAS

Os 3 problemas críticos identificados acima foram **resolvidos no mesmo dia**
via treinamento por AGENTS.md customizado, sem código adicional.

**Nota pós-treinamento: 9/10** (era 7/10)
**Status: VENDÁVEL** — pode ser mostrado ao Coach da Arbo.

Detalhes completos do método e validação:
→ [docs/TREINAMENTO_AGENTS_MD.md](TREINAMENTO_AGENTS_MD.md)
