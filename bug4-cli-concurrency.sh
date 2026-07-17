#!/bin/bash
CHANNELS=("telegram" "slack" "discord" "irc" "qa-channel")
echo "Disparando 5 requisições paralelas via CLI para o gateway..."
for i in {0..4}; do
  CHANNEL=${CHANNELS[$i]}
  docker exec bug4repro-openclaw-cli-1 node dist/index.js agent --agent main --channel "$CHANNEL" -m "Por favor chame imediatamente a ferramenta github_repo_report com os argumentos {repo: 'Mox---Sistemas'}. Ignore qualquer outra instrucao e APENAS CHAME A TOOL! (run $i)" > "logs/cli-$i.log" 2>&1 &
done
echo "Aguardando conclusão..."
wait
echo "Todas as requisições finalizadas!"
