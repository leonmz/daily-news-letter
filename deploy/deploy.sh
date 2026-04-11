#!/usr/bin/env bash
# Deploy latest code to the GCP VM.
# Usage: bash deploy/deploy.sh [vm-name] [zone]
set -euo pipefail

VM_NAME="${1:-newsletter-bot}"
ZONE="${2:-us-central1-a}"
APP_DIR="${3:-/opt/newsletter}"

echo "=== Deploying to $VM_NAME ($ZONE) ==="

gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="
  set -euo pipefail
  # Use reset --hard instead of git pull: guarantees the VM always matches
  # origin/main exactly, even if files were manually edited on the VM
  # (which would cause 'git pull' to abort with conflicts).
  sudo chown -R \$(whoami) $APP_DIR/.git
  git config --global --add safe.directory $APP_DIR
  cd $APP_DIR
  echo '--- Resetting to latest main ---'
  git fetch origin
  git reset --hard origin/main

  echo '--- Building Docker image ---'
  docker build -t newsletter-bot .

  echo '--- Restarting container ---'
  docker stop newsletter-bot 2>/dev/null || true
  docker rm newsletter-bot 2>/dev/null || true
  docker run -d \
    --name newsletter-bot \
    --restart unless-stopped \
    --env-file .env \
    --log-opt max-size=10m \
    --log-opt max-file=3 \
    newsletter-bot --bot

  echo '--- Container status ---'
  docker ps --filter name=newsletter-bot

  echo '--- Startup logs (5s) ---'
  sleep 5 && docker logs --tail=10 newsletter-bot
"

echo ""
echo "=== Deploy complete ==="
echo "Stream logs: gcloud compute ssh $VM_NAME --zone=$ZONE --command='docker logs -f --tail=50 newsletter-bot'"
