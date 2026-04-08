#!/usr/bin/env bash
# Deploy latest code to the GCP VM.
# Usage: bash deploy/deploy.sh [vm-name] [zone]
set -euo pipefail

VM_NAME="${1:-market-bot}"
ZONE="${2:-us-central1-a}"

echo "=== Deploying to $VM_NAME ($ZONE) ==="

gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="
  cd ~/app
  git pull

  # Use docker compose if available, otherwise fall back to docker run
  if docker compose version &>/dev/null; then
    docker compose up -d --build
    echo ''
    docker compose ps
  else
    echo 'docker compose not available, using docker run...'
    docker build -t market-bot .
    docker stop market-bot 2>/dev/null || true
    docker rm market-bot 2>/dev/null || true
    docker run -d \
      --name market-bot \
      --restart unless-stopped \
      --env-file .env \
      --log-opt max-size=10m \
      --log-opt max-file=3 \
      market-bot
    echo ''
    docker ps --filter name=market-bot
  fi
"

echo ""
echo "=== Deploy complete ==="
echo "Logs: gcloud compute ssh $VM_NAME --zone=$ZONE --command='cd ~/app && docker compose logs -f --tail=50'"
