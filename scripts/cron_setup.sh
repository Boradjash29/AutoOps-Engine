#!/bin/bash
# cron_setup.sh

CRON_CMD_CLEANUP="0 2 * * * /bin/bash /home/jash/AutoOps-Engine/automation/cleanup.sh >> /home/jash/AutoOps-Engine/logs/cron.log 2>&1"
CRON_CMD_BACKUP="0 3 * * * /bin/bash /home/jash/AutoOps-Engine/automation/backup.sh >> /home/jash/AutoOps-Engine/logs/cron.log 2>&1"

(crontab -l 2>/dev/null | grep -v "cleanup.sh" | grep -v "backup.sh"; echo "$CRON_CMD_CLEANUP"; echo "$CRON_CMD_BACKUP") | crontab -

echo "Cron jobs installed successfully."
