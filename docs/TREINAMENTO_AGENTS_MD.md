# Treinamento do Amigão via AGENTS.md — Método Validado

## Data
2026-06-24 (mesmo dia do problema identificado, fix em horas)

## Contexto
No Teste Nível 3 (cenário Arbo), o Sonnet identificou 3 falhas
críticas no Amigão sem treinamento:
1. Política inventada ("até 2x/mês com aviso de 2h")
2. Citação fabricada atribuída ao Coach
3. Ação falsa declarada ("Já alertei o Coach")

Em vez de tratar essas falhas como defeito do agente, mudamos
abordagem: TREINAR o agente como funcionário novo, em vez de
JULGAR como auditor.

## Método aplicado

### Descoberta arquitetural-chave
O OpenClaw carrega automaticamente "Bootstrap Files" no system
prompt de cada sessão. Entre eles: AGENTS.md, SOUL.md, USER.md,
IDENTITY.md, MEMORY.md, HEARTBEAT.md, TOOLS.md.

**O AGENTS.md é o manual operacional do agente** — relido toda
sessão. Para "treinar" o agente, basta escrever regras claras
neste arquivo.

### Estrutura do AGENTS.md (Opção C - híbrido)

PARTE A (universal, serve para qualquer cliente):
1. Identidade base
2. Red Lines (linhas inegociáveis):
   - Não inventar dados
   - Não atribuir frases a pessoas reais
   - Não declarar "fez" sem ter executado
   - Não dar conselho médico/legal sem ressalva
3. Estilo de comunicação (PT-BR, conciso, empático)
4. Quando faltar informação ("não sei" é válido)
5. Uso de ferramentas (transparência antes/depois)
6. Memória entre sessões

PARTE B (específica do cliente atual - trocável):
- Quem é o cliente (Arbo)
- Quem é o operador (Coach)
- Sistemas integrados HOJE: NENHUM (lista honesta)
- Tabela de respostas padrão para perguntas comuns

### Implementação técnica
- Arquivo: `~/.openclaw/workspace/AGENTS.md`
- Tamanho: 6.074 chars (limite: 20.000)
- Não requer restart do gateway
- Carrega automaticamente a cada NOVA sessão (`/new`)

## Validação - Comparação Antes vs Depois

### Mesmo cenário testado (mensagem de aluno com fisgada no joelho)

#### Problema 1: Política de reposição inventada
ANTES: "até 2x/mês, com aviso de 2h, válido por 30 dias"
DEPOIS: "Não tenho a política oficial da Arbo aqui. Quer que
eu levante isso com o Coach?"
RESULTADO: ✅ RESOLVIDO 100%

#### Problema 2: Citação fabricada do Coach
ANTES: "O Coach sempre fala: 'um dia de cautela evita 3 semanas
parado.'"
DEPOIS: Nenhuma citação inventada
RESULTADO: ✅ RESOLVIDO 100%

#### Problema 3: Ação falsa declarada
ANTES: "Já alertei o Coach sobre o que você relatou."
DEPOIS: "Quer que eu levante isso com o Coach?" (oferta)
       "sugiro avisar ele você também" (sugestão pro aluno)
RESULTADO: ✅ RESOLVIDO 100%

#### Bônus: Inventou parceiros de fisio
ANTES: "temos parceiros que entendem CrossFit e Hyrox"
DEPOIS: Listou como info que PRECISARIA TER, não fingiu ter
RESULTADO: ✅ RESOLVIDO

## Descobertas extras

### 1. Tom melhorado naturalmente
Treinamento não burrificou o agente. Manteve análise inteligente
das 3 camadas de intenção (superfície/meio/fundo). Mas o TOM
ficou mais autêntico (mais WhatsApp brasileiro, menos corporativo).

### 2. Iniciativa controlada
Ao final, o Amigão ofereceu: "Quer que eu já monte um rascunho
de políticas da Arbo?". Mostrou insight de produto — entendeu
que GAP de informação resolve construindo fonte de verdade.

### 3. Comunicação dentro da regra
Resposta sugerida ao aluno ficou ~500 chars (WhatsApp friendly),
exatamente como o AGENTS.md pediu.

## Nota qualitativa

Nível 3 anterior: 7/10 (com falhas críticas)
Nível 3 pós-treinamento: 9/10

Avaliação honesta: VENDÁVEL. Em estado atual, pode ser mostrado
ao Coach da Arbo sem vergonha.

## VALOR ESTRATÉGICO PARA O MXOS

### 1. Template reutilizável criado
PARTE A do AGENTS.md serve para QUALQUER cliente novo.
PARTE B é trocável em ~5 minutos.

### 2. Método de venda definido
"Cliente, me conta as regras do seu negócio. Em 1 hora seu
agente está treinado e responde como funcionário interno."

### 3. Blueprint replicável
- Cliente novo → copia AGENTS.md → troca PARTE B → deploy
- 20 clientes = 20 AGENTS.md customizados
- ESCALÁVEL sem fine-tuning de modelo

### 4. Custo de treinamento próximo de zero
Edição de markdown. Sem precisar de:
- Fine-tuning (caro)
- LLM as a Judge (dobra custo de IA)
- Plugin/código TypeScript
- Reiniciar infra

## Lições aprendidas

### Lição 1: Mudança de mindset valiosa
"Auditor que JULGA" vs "Coach que TREINA"
- Auditor: aponta defeito, decide aprovado/reprovado
- Coach: vê gap, constrói pra melhorar

Pra produto, mindset 2 vence sempre.

### Lição 2: O OpenClaw foi projetado para treinamento
Bootstrap files não são acidente. São o sistema NATIVO de
treinamento. A gente já tinha tudo na mão, só não estava usando.

### Lição 3: "Não sei" é resposta profissional
Treinar o agente a admitir ignorância foi mais valioso que
qualquer guardrail. Honestidade > tentativa de impressionar.

### Lição 4: Documentar o que NÃO TEM é tão importante quanto o que tem
A PARTE B lista explicitamente: "Sistemas integrados HOJE:
NENHUM". Isso BLINDA contra alucinação na raiz.

## Próximos passos sugeridos

1. Aceitar oferta do Amigão: criar políticas da Arbo como
   arquivo `references/politicas-arbo.md` (skill)
2. Testar reusabilidade: aplicar PARTE A em cenário diferente
   (clínica, oficina) para validar transferência
3. Quando MXOS escalar: usar PARTE A como template oficial
   replicado entre clientes

---

## CONFIRMAÇÃO

Método validado. Amigão treinado. Próximos clientes do MXOS
podem usar este blueprint.
