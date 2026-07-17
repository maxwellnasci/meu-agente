#!/bin/bash
# ~/.openclaw/heartbeat-monitor.sh

GATEWAY_URL="http://127.0.0.1:18789/healthz"
CHECK_INTERVAL=5
MAX_FAILURES=3
CONTAINER_NAME="openclaw-openclaw-gateway-1"
REPORT_DIR="/home/max/.openclaw/logs"

# Ensure the logs directory exists on the host
mkdir -p "$REPORT_DIR"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting heartbeat monitor for $CONTAINER_NAME..."

failure_count=0

while true; do
  # Perform a silent curl, outputting HTTP status code. Timeout is 3s.
  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$GATEWAY_URL")
  
  if [ "$status" != "200" ]; then
    failure_count=$((failure_count + 1))
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Healthcheck failed (status: $status). Failure count: $failure_count/$MAX_FAILURES"
  else
    if [ "$failure_count" -gt 0 ]; then
      echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Healthcheck recovered."
    fi
    failure_count=0
  fi

  if [ "$failure_count" -ge "$MAX_FAILURES" ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Threshold reached ($MAX_FAILURES consecutive failures). Sending SIGUSR2 to node process..."
    
    # 1. Log the exact time and context
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Triggering diagnostic report..." >> "$REPORT_DIR/heartbeat-incidents.log"
    
    # 2. Get the PID of the node process running inside the container
    NODE_PID=$(docker exec "$CONTAINER_NAME" ps aux | grep 'node' | grep 'gateway' | grep -v 'grep' | awk '{print $2}')
    
    if [ -n "$NODE_PID" ]; then
      # 3. Send SIGUSR2 to the node process inside the container
      docker exec "$CONTAINER_NAME" kill -USR2 "$NODE_PID"
      echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] SIGUSR2 sent to PID $NODE_PID inside container." >> "$REPORT_DIR/heartbeat-incidents.log"
      echo "SIGUSR2 sent. Waiting 60 seconds before resuming checks..."
      
      # Reset failure count and sleep 60s to prevent spamming reports
      failure_count=0
      sleep 60
    else
      echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Could not find node PID in container. Container might be down or restarting." >> "$REPORT_DIR/heartbeat-incidents.log"
      failure_count=0
      sleep 10
    fi
  fi

  sleep "$CHECK_INTERVAL"
done
