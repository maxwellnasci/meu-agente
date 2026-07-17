#!/bin/bash
CONTAINER="bug4repro-openclaw-gateway-1"
# We want the node process, not the tini wrapper
PID=$(docker top $CONTAINER | grep 'node dist/index.js gateway' | grep -v 'tini' | awk '{print $2}')
LOGFILE="/home/max/Documentos/Kali Linux/meu-agente/bug4-monitor.log"

echo "Starting monitor on host PID $PID" > "$LOGFILE"
while true; do
  echo "=== $(date -Iseconds) ===" >> "$LOGFILE"
  cat /proc/$PID/status | grep -E "State|Threads|VmRSS|VmData" >> "$LOGFILE"
  echo "FD count: $(ls /proc/$PID/fd 2>/dev/null | wc -l)" >> "$LOGFILE"
  echo "TCP stats:" >> "$LOGFILE"
  cat /proc/$PID/net/tcp 2>/dev/null | wc -l | awk '{print $1 " TCP sockets"}' >> "$LOGFILE"
  
  # Also check if it's deadlocked in libuv by doing a quick CPU check
  ps -p $PID -o %cpu= >> "$LOGFILE"
  
  sleep 1
done
