# Estado Atual do Projeto

- **Nome do projeto:** MEU AGENTE (OpenClaw isolado para aprendizado)
- **Objetivo:** aprender agentes autônomos com máxima segurança
- **Modelo/cérebro:** DeepSeek V3 (`deepseek/deepseek-chat`) — V4-flash disponível para migração
- **Versão OpenClaw:** v2026.6.9 (estável)
- **Data da última atualização:** 2026-06-23

---

## ⚠️ ALERTA DE SEGURANÇA ATIVO

**O sandbox está DESLIGADO.** `sandbox.mode: "off"` foi configurado temporariamente para validar o primeiro boot.
**Isso significa que o agente NÃO tem isolamento de contêiner.** Pode, em tese, executar comandos que afetam o sistema host se tiver ferramentas disponíveis.

**Situação mitigante (parcial):** `workspaceAccess: "none"` permanece ativo — o agente não tem acesso ao filesystem do host via volume. Mas não há sandbox de execução.

**O risco real é baixo agora** porque o agente não possui skills habilitadas, mas **religar o sandbox é prioridade antes de qualquer sessão de trabalho real.**

---

## Checklist do que JÁ foi feito:

- [x] ✅ Ambiente mapeado (Node v24.16, Docker ativo, 389GB livres)
- [x] ✅ Auditoria de segurança do docker-compose (sem privileged, cap_drop, no-new-privileges)
- [x] ✅ Pastas de estado criadas (~/.openclaw, workspace, ~/.openclaw-auth-profile-secrets)
- [x] ✅ .env criado com token gateway + chave DeepSeek
- [x] ✅ .env protegido pelo .gitignore (não vaza no git)
- [x] ✅ openclaw.json com gateway.mode: "local" + cron desabilitado
- [x] ✅ pnpm v11.9.0 instalado
- [x] ✅ Imagem Docker openclaw:local construída (758MB)
- [x] ✅ Container `openclaw-openclaw-gateway-1` subiu e ficou estável
- [x] ✅ Plugin @openclaw/deepseek-provider instalado via `openclaw doctor --fix`
- [x] ✅ Plugin registry reconstruído (54/78 plugins indexados)
- [x] ✅ Primeira conversa bem-sucedida com DeepSeek V3
- [x] ✅ Portas validadas sem conflito com n8n (5678) e postgres (5432)

## Checklist do que FALTA (prioridade):

- [ ] 🔴 **URGENTE: Religar sandbox** (`sandbox.mode: "all"`) + configurar `docker.sock` no compose
- [ ] 🟡 Migrar para DeepSeek V4-flash (disponível na UI do OpenClaw, mas precisa de litellm ou atualização do provider)
- [ ] 🟡 Configurar `gateway.controlUi.allowedOrigins` permanentemente no openclaw.json
- [ ] 🟡 Corrigir aviso de memória semântica (desabilitar `memorySearch` ou configurar OpenAI key)
- [ ] 🟢 Explorar concessão gradual de ferramentas ao agente (leitura → escrita → execução)
- [ ] 🟢 Documentar e aplicar aprendizados no projeto MXOS

---

## Estado dos arquivos de configuração

| Arquivo | Localização | Status |
|---|---|---|
| openclaw.json | `~/.openclaw/openclaw.json` | ✅ Ativo — fora do git |
| .env | `openclaw/.env` | ✅ Protegido pelo .gitignore |
| state/openclaw.sqlite | `~/.openclaw/state/` | ✅ Ativo — fora do git |
| Imagem Docker | `openclaw:local` (758MB) | ✅ Construída localmente |
