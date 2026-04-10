#!/usr/bin/env bash
# Deploy latest code to the GCP VM.
# Usage: bash deploy/deploy.sh [vm-name] [zone]
set -euo pipefail

VM_NAME="${1:-newsletter-bot}"
ZONE="${2:-us-central1-a}"
APP_DIR="${3:-~/newsletter}"

echo "=== Deploying to $VM_NAME ($ZONE) ==="

gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="
  set -euo pipefail
  cd $APP_DIR
  echo '--- Pulling latest code ---'
  git pull

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
