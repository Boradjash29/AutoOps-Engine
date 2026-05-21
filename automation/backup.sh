#!/bin/bash
# backup.sh - Compresses logs

LOG_DIR="/home/jash/AutoOps-Engine/logs"
BACKUP_DIR="/home/jash/AutoOps-Engine/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup..."
tar -czf "$BACKUP_DIR/logs_backup_$TIMESTAMP.tar.gz" -C "$LOG_DIR" .

# Remove backups older than 7 days
find "$BACKUP_DIR" -type f -name "*.tar.gz" -mtime +7 -exec rm {} \;

echo "[$(date)] Backup completed: logs_backup_$TIMESTAMP.tar.gz"
