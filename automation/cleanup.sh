#!/bin/bash
# cleanup.sh - Deletes old logs and cleans up Docker

LOG_DIR="/home/jash/AutoOps-Engine/logs"
echo "[$(date)] Starting maintenance cleanup..."

# Delete logs older than 7 days
find "$LOG_DIR" -type f -name "*.log" -mtime +7 -exec rm {} \;

# Docker prune: unused images, dangling volumes, and exited containers
docker system prune -a -f --volumes

echo "[$(date)] Cleanup finished."
