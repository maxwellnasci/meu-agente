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

---

## Processos zumbi de sessões `docker exec -i` órfãs (encontrado 2026-08-02)

### O que aconteceu
Um processo `cat` ficou preso consumindo **99.8% de CPU (um núcleo
inteiro) por mais de 4 dias** no servidor Contabo, sem ninguém notar
até um relatório externo apontar o PID. Origem: uma sessão interativa
`docker exec -i openclaw-openclaw-gateway-1 sh -c "cat > /tmp/check-
token.js"`, provavelmente rodada durante o teste de token do WhatsApp
da Etapa 5 da migração (2026-07-29), cuja conexão (SSH/terminal) caiu
no meio sem fechar o stdin direito.

### Causa raiz técnica
`docker exec -i` mantém um pipe entre o cliente (seu terminal/SSH) e o
processo dentro do container. Quando a conexão cai de forma anormal
(sem `Ctrl-D`/EOF limpo), esse pipe pode ficar num estado inconsistente
em vez de simplesmente fechar. Neste caso, `/proc/<pid>/fd` mostrou o
`stdin` (fd 0) e o `stdout` (fd 1) do `cat` apontando pro **mesmo
pipe** — o processo ficava lendo e reescrevendo nele mesmo, num loop
infinito, sem nunca alcançar EOF e sem nunca escrever o arquivo de
destino de verdade (por isso o arquivo esperado não existia). Resultado:
CPU no talo pra sempre, silenciosamente, sem afetar a aplicação real
(o `cat` órfão não tem nenhuma relação de processo-pai/filho com o
gateway do Amigão — só compartilha o namespace do container via
`docker exec`).

### Como confirmar antes de matar (nunca matar às cegas)
```bash
# 1. Existe mesmo? Tempo de execução e CPU real
ps -eo pid,ppid,user,etime,pcpu,stat,cmd | grep <PID>

# 2. Mapeia o PID "de dentro do container" pro PID real do host
sudo grep NSpid /proc/<PID_HOST>/status

# 3. Que arquivo ele deveria ter escrito? Existe?
docker exec <container> sh -c 'ls -la /caminho/do/arquivo'

# 4. Pra onde apontam os FDs — é aqui que aparece o loop de pipe
sudo ls -la /proc/<PID>/fd/

# 5. Confirma que NÃO é o processo principal do container
docker inspect <container> --format '{{.State.Pid}}'   # PID real da app
ps -eo pid,ppid,cmd | grep -E '<PID_do_processo_suspeito>|<PID_da_app>'
```
Só depois dessa cadeia de evidência (existe → o que ele fazia → por
que travou → não tem relação com a app real) é seguro matar
(`kill -9` na cadeia inteira: processo → shell pai → `docker exec`
no host).

### Prática recomendada pra evitar (e pra detectar cedo)
- **Fechar sessões `docker exec -i` interativas de forma limpa**
  (`exit`/`Ctrl-D`), nunca simplesmente fechar o terminal ou deixar a
  conexão SSH cair no meio de um comando com stdin aberto.
- Preferir, quando possível, `docker exec` sem `-i` (ou com heredoc
  fechado, `<<'EOF' ... EOF`) em vez de pipe interativo aberto —
  reduz a chance de deixar uma sessão pendurada.
- **Checar processos órfãos periodicamente** em produção:
  `ps aux --sort=-%cpu | head -10` de vez em quando, especialmente
  depois de sessões de debug via `docker exec` que envolveram conexão
  SSH instável ou testes manuais (como os testes de token/credenciais).
- Um único processo estacionado em ~100% de CPU por dias pode passar
  despercebido num host com múltiplos containers e carga variável —
  não presuma que "load average normal" significa "nada preso"; some
  o `%CPU` por processo individual (`top`/`ps --sort=-%cpu`), não só o
  load average agregado.

Investigação completa, com evidência real de cada etapa, em
[SESSAO_2026-08-02.md](SESSAO_2026-08-02.md#processo-zumbi-encontrado-e-resolvido-no-contabo).
