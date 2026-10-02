# Produção (Contabo): ativação do ORCHESTRATOR_API_TOKEN — 02/10/2026 (horários em UTC)

Registro do que foi feito no servidor de produção (Contabo) para ativar a
autenticação por token entre o gateway OpenClaw e o Orchestrator. Nenhum
valor de token, chave ou senha aparece neste documento — só nomes de
variáveis e caminhos.

Complementa [autenticacao-token.md](autenticacao-token.md), que documenta o
mecanismo (código, middleware, extensão) validado antes no ambiente local.

---

## 1. Estado inicial

- **CONFIRMADO:** o Orchestrator do Contabo rodava a versão "token opcional"
  (`verify_api_token` presente, mas sem token configurado liberava tudo —
  `POST /v1/turn` com corpo inválido respondia `422`, não `401`).
- **CONFIRMADO:** nenhum dos dois `.env` (`/root/openclaw/.env` e
  `/root/meu-agente-orchestrator/.env`) tinha `ORCHESTRATOR_API_TOKEN`.

## 2. Token e backup

- **CONFIRMADO:** backup feito antes de qualquer escrita, em uma pasta de
  backup datada no servidor (nome e local ficam fora deste documento;
  pasta `700`, arquivos `600`):
  os dois `.env` e o `docker-compose.yml` do gateway, conferidos idênticos
  aos originais.
- **CONFIRMADO:** token novo gerado **no próprio servidor**
  (`openssl rand -hex 32`), guardado só numa variável de shell, acrescentado
  com `>>` ao final de `/root/openclaw/.env` e de
  `/root/meu-agente-orchestrator/.env`, e a variável limpa com `unset`.
- **CONFIRMADO:** mesmo valor nos dois arquivos (comparação por sha256),
  exatamente 1 linha `ORCHESTRATOR_API_TOKEN` em cada, demais linhas
  preservadas.

## 3. Gateway

- **CONFIRMADO:** `openclaw-gateway` e `openclaw-cli` recriados com
  `docker compose up -d --force-recreate` em `/root/openclaw/`. Nenhum
  outro container foi tocado.
- **CONFIRMADO:** o compose do gateway carrega `.env` via `env_file`, então
  a variável entrou no container **sem mudança no `docker-compose.yml`**.
  Variável `CARREGADO` no container, sha256 igual ao do `.env` do
  Orchestrator.
- **CONFIRMADO:** o plugin `whatsapp-cloud` da imagem em produção lê
  `process.env.ORCHESTRATOR_API_TOKEN` a cada chamada e envia
  `Authorization: Bearer` quando a variável existe.

## 4. Deploy do Orchestrator

- **CONFIRMADO:** deploy via `scripts/deploy-orchestrator.sh` (pytest local
  157/157 → `rsync` → commit de snapshot no servidor → `docker compose build`
  → `up -d` → `/health` ok), a partir do commit `75bfea9` do repo local, sem
  mudanças soltas.
- **CONFIRMADO:** o deploy levou junto a autenticação **fail-closed** e a
  correção de n8n (`ab220be` — integração n8n ausente aborta o especialista
  de forma explícita; não afeta a rota geral). Dry-run antes do deploy:
  7 arquivos modificados, 0 apagados.
- **CONFIRMADO:** ponto de rollback = commit `72fc9bf` no repo do servidor
  (`/root/meu-agente-orchestrator`). Snapshot novo após o deploy: `0d582e0`.

## 5. Validação

- **CONFIRMADO:** startup sem o aviso "ORCHESTRATOR_API_TOKEN não está
  configurado", sem erro nem traceback.
- **CONFIRMADO:** `POST /v1/turn` **sem token**, com corpo válido → `401`.
- **CONFIRMADO:** mensagem real do WhatsApp, via gateway → `POST /v1/turn`
  `200`.
- **CONFIRMADO:** zero ocorrências de "Orchestrator turn failed" no gateway
  após o deploy.

## 6. Incidente: túnel duplicado no Kali

- **CONFIRMADO:** durante os testes, o WhatsApp respondia "Desculpa, tive um
  problema para processar sua mensagem agora…" sem nenhum registro no
  Contabo. Causa: um **segundo connector do mesmo túnel Cloudflare** rodando
  no Kali recebia parte dos webhooks; o gateway local do Kali não alcança o
  Orchestrator e caía na mensagem de fallback.
- **CONFIRMADO:** o processo vinha da unit **de usuário**
  `~/.config/systemd/user/cursor-cli-tunnel.service` (por isso
  `systemctl is-active cloudflared` do sistema mostrava `inactive`).
- **CONFIRMADO:** a unit foi parada e desabilitada (arquivo mantido). Nada
  dependia dela; ela é que tem `Wants=cursor-cli-bridge.service`, que segue
  ativa. Depois disso, a mensagem de teste chegou ao Contabo com `200`.
- **Lição:** nunca rodar o túnel de produção em outra máquina. Em fallback
  ou sumiço de mensagem, checar `pgrep -ax cloudflared` no Kali antes de
  investigar o servidor.
- **Não relacionado ao token:** a falha aconteceu antes de a requisição
  chegar ao Orchestrator.

## 7. Em aberto / hipóteses

- **EM ABERTO:** a tool `ask_orchestrator` (plugin `orchestrator-bridge`) da
  imagem v4 do gateway não tem suporte a token e deve receber `401`
  (SUPOSIÇÃO: ainda não testado em produção; o plugin não tem código de
  token) até sair imagem nova. Não afeta o WhatsApp, que usa o caminho direto do
  `whatsapp-cloud`.
- **SUPOSIÇÃO:** a unit `cursor-cli-tunnel.service` foi criada para a ponte
  do Cursor e reaproveitou o túnel do WhatsApp por engano.
- **NÃO VERIFICADO:** se existe webhook ou pull agendado no servidor (as docs
  não citam nenhum; o crontab do servidor não foi lido).
- **NÃO VERIFICADO:** `ORCHESTRATOR_N8N_URL` e `ORCHESTRATOR_N8N_API_KEY`
  estão preenchidos no `.env` do Orchestrator, mas não foi conferido se os
  valores estão corretos.

## 8. Pendências

- [ ] Apagar a pasta de backup datada no servidor (nome e local ficam fora
      deste documento) depois de alguns dias estáveis — guarda cópias dos
      `.env`.
- [ ] Gerar e publicar imagem nova do gateway com suporte a token no
      `orchestrator-bridge`.
- [ ] **Antes de qualquer deploy futuro:** o `rsync` do
      `deploy-orchestrator.sh` exclui o `.env`, então o `.env` do servidor é
      a fonte do token. Não apagar nem recriar sem a linha
      `ORCHESTRATOR_API_TOKEN` — sem ela, o Orchestrator responde `401` a
      tudo e o WhatsApp para.
