# Meu Agente — Laboratório de Agentes Autônomos Seguros

> Construindo e validando agentes de IA com isolamento real, 
> defense in depth e arquitetura pronta para produção.

## 🛡️ Status

- ✅ Agente operacional em sandbox Docker isolado
- ✅ DeepSeek V4-pro como cérebro
- ✅ 8 camadas de defense in depth validadas
- ✅ Documentação viva e auditoria multi-IA
- ✅ Nível 3 testado — cenário MXOS-like com aprendizados críticos documentados
- 🚧 Próxima fase: Supervisor (LLM as a Judge) + integrações reais

## 📌 O que é

Um laboratório técnico para construir, isolar e validar agentes autônomos de IA — usando OpenClaw, Docker e DeepSeek — com foco em segurança aplicada (defense in depth) antes de produção.

## 🎯 Por que existe

Estudo de caso para arquitetura segura de agentes autônomos voltados para PMEs brasileiras. Validar tecnicamente o conceito antes de aplicar em soluções comerciais de "funcionários digitais" (atendimento, agendamento, cobrança automatizados).

## 🏰 Arquitetura de Segurança — 8 Camadas

1. **Container Docker isolado** — Sub-container efêmero por sessão
2. **Drop de privilégio** — Roda como usuário `sandbox`, nunca root
3. **Hash pinning** — Imagens com SHA256 fixo (anti supply-chain)
4. **Tool policy** — Sistema de allow/deny: bloqueia `cron`, `gateway`, `nodes` (deny) E filtra ferramentas não autorizadas via allowlist (allow) — só skills explicitamente liberadas chegam ao agente
5. **Cache de sessão** — Sandbox isolado por sessão, destruído no fim
6. **workspaceAccess: none** — Agente cego para o filesystem do host
7. **NetworkMode: none** — Sandbox sem internet (anti-exfiltração)
8. **Workspace read-only** — Volume montado em modo somente leitura

## 🛠️ Stack

- **OpenClaw** v2026.6.9 (agente autônomo open-source)
- **Docker** + docker-compose (isolamento)
- **DeepSeek V4-pro / V4-flash** (LLM)
- **Kali Linux** (host)
- **Node.js** + pnpm (runtime)

## 🤖 Workflow Multi-IA

Este projeto usa um protocolo de múltiplas IAs trabalhando em papéis distintos:

- **Claude (chat)** — Orquestrador / parceiro de estratégia
- **Antigravity Sonnet** — Auditor / analista de segurança
- **Antigravity Gemini** — Executor de tarefas validadas
- **Claude Code (terminal)** — Auditor local com acesso aos arquivos

Detalhes em [docs/FLUXO_MULTI_IA.md](docs/FLUXO_MULTI_IA.md).

## 📁 Estrutura
meu-agente/

├── docs/

│   ├── ESTADO_ATUAL.md          # Status atual do projeto

│   ├── ARQUITETURA_SEGURANCA.md # Detalhes das 8 camadas

│   ├── FLUXO_MULTI_IA.md        # Protocolo multi-IA

│   ├── PROXIMOS_PASSOS.md       # Roadmap

│   ├── SESSAO_2026-06-23.md     # Log da sessão de setup

│   ├── SESSAO_2026-06-24.md     # Log da sessão de refinamento

│   ├── TESTE_NIVEL_1.md         # Validação capacidades básicas

│   ├── TESTE_NIVEL_2.md         # Sub-agentes paralelos + auth

│   ├── TESTE_NIVEL_3.md         # Cenário MXOS-like + aprendizados críticos

│   └── TESTE_SANDBOX.md         # Validação do isolamento

├── ANALISE.md                   # Auditoria inicial de segurança

├── .gitignore                   # Protege .env e código de terceiros

└── README.md                    # Este arquivo

## 🎓 Aprendizados-chave

- **"Sem prova, sem aprovação"** — Toda config crítica validada com schema/doc oficial antes de aplicar
- **Defense in depth funciona** — Validado em produção com teste `whoami` retornando `sandbox` (não host, não root)
- **Auditoria multi-IA pega o que IA única não pega** — Sonnet encontrou 2 campos inventados que Gemini não percebeu
- **Documentação viva** — Cada sessão registrada permite retomar contexto e onboard de outras IAs
- **Sandbox sem rede externa** — `NetworkMode: none` impede exfiltração de dados, comunicação com C2 e download de malware
- **Alucinação elegante é mais perigosa que erro óbvio** — Resposta bem formatada com dado inventado passa pela revisão humana; erro grosseiro não passa
- **O moat do MXOS é EXECUÇÃO, não análise** — Qualquer LLM produz texto bonito; integrar com sistemas reais do cliente é o diferencial

## 🚧 Próximos passos

- Implementar Supervisor (LLM as a Judge) para validar respostas antes do envio
- Integrações reais: n8n + WhatsApp Business API + Supabase
- Aplicação dos aprendizados no projeto MXOS (funcionários digitais para PMEs)

## 👤 Sobre

Construído por **Max** — consultor de automação e IA em Curitiba (BR).

Foco: construir agentes autônomos seguros para pequenas e médias empresas brasileiras (clínicas, oficinas, escritórios). Atualmente estudando cibersegurança e validando arquiteturas de produção com isolamento real.

Outros projetos: Arbo — PWA para coaching esportivo (Hyrox/CrossFit).
