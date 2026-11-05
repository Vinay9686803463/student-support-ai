#!/bin/bash

set -e

PROJECT_DIR="/home/vinay/Windows File/student-support-ai"
BACKUP_ROOT="/home/vinay/Windows File/StudentSupportAI_Backups"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_DIR="$BACKUP_ROOT/$DATE"

mkdir -p "$BACKUP_DIR"

echo "Creating Student Support AI backup..."

rsync -av \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='venv' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='node_modules' \
  "$PROJECT_DIR/" "$BACKUP_DIR/"

git -C "$PROJECT_DIR" bundle create \
  "$BACKUP_DIR/student-support-ai-history.bundle" --all

cd "$BACKUP_ROOT"

zip -qr "StudentSupportAI_$DATE.zip" "$DATE"

echo "BACKUP COMPLETED!"
echo "Backup saved at: $BACKUP_DIR"
echo "ZIP saved at: $BACKUP_ROOT/StudentSupportAI_$DATE.zip"
