# Sessão 2026-08-22 — Orquestrador conectado ao Gateway/n8n em produção (via Antigravity/Gemini)

## Contexto e proveniência

Troubleshooting feito pelo Max usando o Antigravity (Gemini) **direto no
terminal do Contabo**, não nesta sessão do Claude Code. Documentação
original escrita pelo próprio Antigravity em
`/root/meu-agente-orchestrator/DOCUMENTACAO_ARQUITETURA_E_ERROS.md` (só no
servidor); trazida pro repo em 2026-08-24 (ver marco correspondente em
[ESTADO_ATUAL.md](ESTADO_ATUAL.md)) depois de confirmar, com evidência real
de log (`[whatsapp-cloud] WhatsApp Cloud reply started` às 2026-08-22
11:22 UTC), que o troubleshooting abaixo bate com o que rodou em produção.
Conteúdo abaixo é o original do Antigravity, sem edição de conteúdo técnico.

## Arquitetura do sistema (conforme descrita pelo Antigravity)

O sistema foi evoluído de uma arquitetura estática (n8n + Evolution API)
para um modelo de Agentes Autônomos. A stack é composta por:

1. **WhatsApp Cloud API (Meta)**: recebe e envia mensagens via Webhook oficial.
2. **OpenClaw Gateway (porta 18789)**: container Docker que atua como proxy
   de segurança e porteiro da aplicação. Traduz o Webhook do WhatsApp e
   encaminha a requisição via HTTP POST.
3. **Python Orchestrator + LangGraph (porta 8000)**: o cérebro do sistema.
   Gerencia o estado, decide a intenção da mensagem (roteamento) e determina
   qual agente (persona/skill) deve ser acionado.
4. **OpenClaw Sandbox**: contêineres temporários gerados dinamicamente para
   execução de ferramentas (tools) do agente.
5. **Modelos LLM**: `deepseek/deepseek-chat` via OpenRouter (roteamento e
   conversação geral).

## Erros enfrentados e soluções (troubleshooting log)

### Erro 1 — Orquestrador inacessível pelo Gateway

- **Sintoma**: o Gateway do OpenClaw tentava acessar o Orquestrador via
  webhook mas recebia "Connection Refused".
- **Causa raiz**: o Orquestrador Python (FastAPI/Uvicorn) estava rodando
  com `HOST=127.0.0.1`. No mundo Docker, `127.0.0.1` restringe o serviço
  apenas ao próprio contêiner, bloqueando comunicação externa.
- **Solução**: editado o `.env` do Orquestrador
  (`/root/meu-agente-orchestrator/.env`), mudado para
  `ORCHESTRATOR_HOST=0.0.0.0`, permitindo escutar conexões de outros
  contêineres.

### Erro 2 — Redes Docker isoladas (DNS incorreto)

- **Sintoma**: mesmo com a porta aberta, o OpenClaw Gateway estava
  configurado para bater em `http://localhost:8000/v1/chat/completions`.
  No Docker, `localhost` do Gateway não é o `localhost` da máquina host
  (Contabo).
- **Causa raiz**: o `docker-compose` cria uma rede bridge. Contêineres
  precisam se comunicar pelo nome do serviço, não por `localhost`.
- **Solução**: variável de ambiente alterada para usar a resolução DNS
  interna do Docker: `ORCHESTRATOR_URL=http://meu-agente-orchestrator-orchestrator-1:8000`
  dentro de `/root/openclaw/.env`.

### Erro 3 — Sandbox bloqueando acesso a diretórios externos (segurança estrita)

- **Sintoma**: quando o Orquestrador tentava delegar uma tarefa pro agente
  `cybersec`, a execução falhava com erro de segurança do sandbox ao
  tentar montar o volume `/opt/claude-skills`. O OpenClaw é seguro por
  padrão e impede acesso a arquivos do host.
- **Causa raiz**: o bind mount estava bloqueado pelas políticas internas
  do runtime do sandbox.
- **Solução**: alterado `/root/.openclaw/openclaw.json`, inserida a flag
  `dangerouslyAllowExternalBindSources: true` no caminho correto da
  hierarquia do JSON (`agents.list.0.sandbox.docker`), permitindo montar a
  pasta `/opt/claude-skills` (read-only) dentro do sandbox do agente
  `cybersec`. **Auditado em 2026-08-24**: escopo confirmado correto — só o
  agente `cybersec` (não o `main`), bind `:ro`, sem segredo exposto no
  diretório montado (43 pastas de skills, conteúdo público).

### Erro 4 — Crash-loop do Gateway por JSON inválido

- **Sintoma**: o Gateway reiniciava infinitamente após a tentativa de
  editar a política do sandbox.
- **Causa raiz**: a chave `dangerouslyAllowExternalBindSources` foi
  colocada acidentalmente dentro de `sandbox` (rejeitada pela validação
  estrita do esquema Zod), em vez de `sandbox.docker`.
- **Solução**: via terminal do Contabo (`jq`), deletada a chave errada e
  aplicada no caminho exato `.agents.list[0].sandbox.docker.dangerouslyAllowExternalBindSources = true`,
  validando a subida saudável e estável do Gateway na porta 18789.

## Próximos passos (registrados pelo Antigravity em 2026-08-22)

- Documentar todas as tools personalizadas adicionadas futuramente.
- Transicionar fluxos pesados e rotineiros do n8n para código Python
  integrado no LangGraph.
- Adicionar logs centralizados usando Prometheus ou LangSmith.

## Nota de continuidade (2026-08-24)

Ver [ESTADO_ATUAL.md](ESTADO_ATUAL.md) para o que foi feito depois desta
sessão: revisão completa do código do orquestrador, hardening de segurança
do especialista n8n (`n8n_guard.py`, mesma filosofia do
`cybersec_guard.py`), e criação de um processo de deploy repetível
(`scripts/deploy-orchestrator.sh`) — antes disso, o deploy pro Contabo era
manual (editar `.env`/`openclaw.json` direto via SSH, sem script nem
histórico versionado).
