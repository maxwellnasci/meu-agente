# Estado Atual do Projeto

- **Nome do projeto:** MEU AGENTE (OpenClaw isolado para aprendizado)
- **Objetivo:** aprender agentes autônomos com máxima segurança
- **Modelo/cérebro:** Selecionável nativamente na interface web (V3, V4-flash, V4-pro)
- **Versão OpenClaw:** v2026.6.9 (confirmado - mais recente disponível)
- **Tentativa de update para v2026.6.10:** realizada em 05/07/2026
- **Resultado da tentativa:** v2026.6.9 é a versão mais atual no repositório oficial. Banner "atualização disponível" aparece antes do código ser publicado no GitHub deles.
- **Backup salvo em:** ~/backup-openclaw-20260705-0646/
- **Sistema:** healthy ✅
- **Servidor:** kernel 6.8.0-134, todos updates aplicados
- **nginx-app-1:** requer início manual após reboot
- **WhatsApp:** ✅ Cloud API oficial (Meta) FUNCIONANDO ponta a ponta (webhook recebe, Amigão responde)
- **Canal ativo:** whatsapp-cloud (extensão customizada), substituindo Baileys/Evolution como canal principal de WhatsApp
- **Baileys/Evolution:** descontinuado como canal principal
- **Túnel público:** Cloudflare Tunnel (whatsapp.mxos.com.br → localhost:18789), serviço systemd permanente, reconexão automática
- **Nova direção:** fork evolutivo do OpenClaw com 2º agente de segurança
- **Próximos passos:** verificação do app pra produção, avaliar migração pro Contabo
- **Data da última atualização:** 2026-07-14

---

## ✅ MARCO — WhatsApp Cloud API funcionando ponta a ponta (2026-07-14)

Primeira mensagem real recebida E respondida pelo Amigão via WhatsApp Cloud
API oficial da Meta. Fluxo completo: WhatsApp → Meta → Cloudflare Tunnel →
OpenClaw Gateway → Amigão (memória, sandbox, DeepSeek) → resposta via Graph API.

- **Infraestrutura:** Cloudflare Tunnel (`whatsapp.mxos.com.br`), serviço
  systemd permanente, não depende do Contabo estar de pé.
- **Canal:** `extensions/whatsapp-cloud/`, implementado como canal real
  (padrão `extensions/sms`), não TaskFlow — garante conversa contínua com
  memória por número de telefone. 16 testes automatizados, typecheck limpo.
- **Credenciais:** token de acesso PERMANENTE via System User (não expira),
  guardado em `~/.openclaw/credentials/whatsapp-cloud.json` (chmod 600).
- **Detalhes completos:** [docs/SESSAO_2026-07-14.md](SESSAO_2026-07-14.md)

---

## ESTADO FINAL DO DIA 2026-06-24

- **Agente "Amigão":** Operacional
- **Modelo:** V4-pro (selecionado na sessão)
- **Sandbox:** Validado (`whoami` retornou "sandbox")
- **Nível de segurança:** *Defense in depth* com 6 camadas implementadas e testadas
- **Autenticação de Sub-agentes:** Corrigida via auth profiles (sqlite)
- **Warnings:** Limpos (allowedOrigins e memorySearch)
- **Status:** Estável, pronto para testar criação de arquivos

---

## ✅ SANDBOX ATIVO — Sistema blindado

**`sandbox.mode: "all"`** está configurado e operacional desde 2026-06-23.
O agente executa comandos em micro-containers descartáveis via `docker.sock`.
O `workspaceAccess: "none"` permanece ativo — o agente não acessa o filesystem do host.

---

## Checklist do que JÁ foi feito:

- [x] ✅ Ambiente mapeado (Node v24.16, Docker ativo, 389GB livres)
- [x] ✅ Auditoria de segurança do docker-compose (sem privileged, cap_drop, no-new-privileges)
- [x] ✅ Pastas de estado criadas (~/.openclaw, workspace, ~/.openclaw-auth-profile-secrets)
- [x] ✅ .env criado com token gateway + chave DeepSeek
- [x] ✅ .env protegido pelo .gitignore (não vaza no git)
- [x] ✅ openclaw.json com gateway.mode: "local" + cron desabilitado
- [x] ✅ pnpm v11.9.0 instalado
- [x] ✅ Imagem Docker openclaw:local reconstruída com Docker CLI interno (809MB)
- [x] ✅ Container `openclaw-openclaw-gateway-1` subiu e ficou estável
- [x] ✅ Plugin @openclaw/deepseek-provider instalado via `openclaw doctor --fix`
- [x] ✅ Plugin registry reconstruído (54/78 plugins indexados)
- [x] ✅ Primeira conversa bem-sucedida com DeepSeek V3
- [x] ✅ Portas validadas sem conflito com n8n (5678) e postgres (5432)
- [x] ✅ **Sandbox ativo e validado em produção** (teste whoami passou)
- [x] ✅ **DeepSeek V4-pro funcional** (selecionável na interface)
- [x] ✅ **Documentação completa no GitHub**
- [x] ✅ **6 camadas de segurança implementadas e testadas**
- [x] ✅ **Correção de auth de sub-agentes** (paste-api-key)
- [x] ✅ **Warnings limpos no gateway** (allowedOrigins, memorySearch)
- [x] ✅ **Acesso SSH configurado** (chave ed25519 no servidor Contabo)

## TESTES DE CAPACIDADE:

- [x] ✅ **Nível 1** — Sandbox validado (whoami, ls, data)
- [x] ✅ **Nível 2** — Sub-agentes paralelos funcionam, auth corrigido confirmado (2026-06-24)
- [x] ✅ **Nível 3** — Cenário MXOS-like testado com aprendizados críticos documentados (2026-06-24)
- [x] ✅ **Nível 3 pós-treinamento** — 3 falhas críticas resolvidas via AGENTS.md customizado (2026-06-24)

## MÉTODO DE TREINAMENTO — VALIDADO ✅

**Treinamento via AGENTS.md: FUNCIONAL**

O OpenClaw injeta automaticamente "Bootstrap Files" no system prompt de cada sessão.
O `AGENTS.md` é o **manual operacional do agente** — relido toda sessão nova.

| Componente | Status |
|---|---|
| AGENTS.md customizado (Parte A — universal) | ✅ Escrito e ativo |
| AGENTS.md customizado (Parte B — Arbo) | ✅ Escrito e ativo |
| Treinamento sem restart de gateway | ✅ Confirmado (`/new` basta) |
| Custo de treinamento | ✅ Zero (só edição de markdown) |
| Template reutilizável para novos clientes | ✅ Parte A é genérica e transferível |

**Falhas críticas do Nível 3 resolvidas:**
- ✅ Política inventada → eliminada
- ✅ Citação fabricada → eliminada
- ✅ Ação falsa declarada → eliminada

Detalhes completos: [docs/TREINAMENTO_AGENTS_MD.md](TREINAMENTO_AGENTS_MD.md)

## PROBLEMAS CONHECIDOS A RESOLVER:

- ~~⚠️ **Alucinação funcional**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ~~⚠️ **Citações fabricadas**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ~~⚠️ **Ações sem integração declaradas como concluídas**~~ → ✅ Resolvido via AGENTS.md (Red Lines)
- ⚠️ **Sem integrações reais** — agente ainda não acessa sistemas da Arbo (agenda, banco, WhatsApp)

## TESTES DE INTEGRAÇÃO (EVOLUTION API):

- [x] ✅ **Max coloca o chip de teste no celular e conecta instância "amigao"**
- [x] ✅ **Primeiro WhatsApp real enviado** via comando `curl` local na Contabo (2026-06-26)

## PRÓXIMOS PASSOS:

- [ ] Configurar webhook na instância "amigao" para receber mensagens
- [ ] Configurar plugin webhooks do OpenClaw (rota evolution-inbound)
- [ ] Construir skill send-whatsapp no OpenClaw workspace
- [ ] Configurar secrets.json (cofre centralizado)
- [ ] Criar `references/politicas-arbo.md` como skill para dar base de conhecimento real ao agente
- [ ] Testar reusabilidade do AGENTS.md Parte A em cenário diferente (clínica, oficina)
- [ ] Aplicar blueprint MXOS em cliente real

---

## Estado dos arquivos de configuração

| Arquivo | Localização | Status |
|---|---|---|
| openclaw.json | `~/.openclaw/openclaw.json` | ✅ Ativo — fora do git |
| .env | `openclaw/.env` | ✅ Protegido pelo .gitignore |
| state/openclaw.sqlite | `~/.openclaw/state/` | ✅ Ativo — fora do git |
| Imagem Docker | `openclaw:local` (809MB, com Docker CLI) | ✅ Construída localmente |
| docker-compose.yml | `openclaw/docker-compose.yml` | ✅ docker.sock + GID 124 ativos |

---

## Nota de Arquitetura — Por que `openclaw/` não está no git do `meu-agente`

A pasta `openclaw/` é um clone do repositório upstream oficial (`github.com/openclaw/openclaw`).
Ela está no `.gitignore` intencionalmente para manter separação entre código de terceiros e o projeto pessoal.
As alterações feitas no `docker-compose.yml` ficam salvas localmente nesta pasta e **devem ser reaplicadas manualmente** caso a pasta seja deletada e reclonada.

### Alterações locais ao docker-compose.yml (não rastreadas pelo git):
```yaml
# Linhas 50-52 — descomentar sandbox:
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
group_add:
  - "124"
```
