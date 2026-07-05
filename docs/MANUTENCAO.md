# Manutenção do Sistema

## Update OpenClaw (processo validado em 05/07/2026)

### Quando atualizar
Verificar banner amarelo na interface web (localhost:18789)

### IMPORTANTE — verificar antes de rodar update
Sempre confirmar se o código foi publicado:
   cd ~/Documentos/Kali\ Linux/meu-agente/openclaw
   git fetch origin
   git log --oneline origin/master -5

Se não houver commits novos = código ainda não publicado.
Aguardar 1-2 dias e tentar novamente.

### Processo seguro de update (quando código disponível)
1. Backup dos arquivos críticos:
   mkdir -p ~/backup-openclaw-$(date +%Y%m%d-%H%M)
   cp ~/.openclaw/openclaw.json ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/AGENTS.md ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/SOUL.md ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/IDENTITY.md ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/USER.md ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/HEARTBEAT.md ~/backup-openclaw-.../
   cp ~/.openclaw/workspace/TOOLS.md ~/backup-openclaw-.../

2. git stash (salva customizações do docker-compose)
3. git pull origin master
4. git stash pop (restaura customizações)
5. docker build -t openclaw:local \
   --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1 .
6. docker compose down
7. docker compose up -d
8. Validar:
   docker compose ps
   curl -s localhost:18789/healthz
   docker exec openclaw-openclaw-gateway-1 node -e \
   "const p = require('./package.json'); console.log(p.version)"

### Arquivos críticos de backup
- ~/.openclaw/openclaw.json (config principal)
- ~/.openclaw/workspace/AGENTS.md (treinamento do agente)
- ~/.openclaw/workspace/SOUL.md
- ~/.openclaw/workspace/IDENTITY.md
- ~/.openclaw/workspace/USER.md
- ~/.openclaw/workspace/HEARTBEAT.md
- ~/.openclaw/workspace/TOOLS.md

### Tempo estimado
- Verificação: 2 minutos
- Backup: 2 minutos
- Build (quando necessário): 5-15 minutos
- Downtime: ~1 minuto
- Total: ~20 minutos

### Customização crítica (não perder!)
A imagem local openclaw:local foi compilada com:
--build-arg OPENCLAW_INSTALL_DOCKER_CLI=1
Isso habilita o sandbox Docker (essencial pro agente).
SEMPRE usar esse argumento ao rebuildar.

### Lição aprendida
O banner "Atualização disponível: v2026.6.10" apareceu
antes do código ser publicado no repositório oficial.
git pull não trouxe commits novos — sistema já estava
na versão mais recente disponível.
Verificar git log antes de qualquer update.
