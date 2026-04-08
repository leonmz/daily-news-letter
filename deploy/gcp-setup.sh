#!/usr/bin/env bash
# One-time GCP e2-micro VM provisioning for the market newsletter bot.
# Prerequisites: gcloud CLI installed and authenticated (gcloud auth login)
set -euo pipefail

# --- Configuration ---
PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
VM_NAME="${1:-market-bot}"
ZONE="us-central1-a"
REPO_URL="https://github.com/leonmz/daily-news-letter.git"

if [[ -z "$PROJECT_ID" ]]; then
  echo "Error: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "=== Creating e2-micro VM (always-free tier) ==="
echo "  Project: $PROJECT_ID"
echo "  VM:      $VM_NAME"
echo "  Zone:    $ZONE"
echo ""

# Enable Compute Engine API if not already
gcloud services enable compute.googleapis.com --project="$PROJECT_ID" 2>/dev/null || true

# Create the VM
gcloud compute instances create "$VM_NAME" \
  --project="$PROJECT_ID" \
  --zone="$ZONE" \
  --machine-type=e2-micro \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --boot-disk-type=pd-standard \
  --tags=market-bot

echo ""
echo "=== VM created. Waiting for SSH readiness... ==="
sleep 20

# Install Docker if not present, then clone repo
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT_ID" --command="
  if ! docker compose version &>/dev/null; then
    echo 'Installing Docker...'
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker.io docker-compose-v2 git
    sudo systemctl enable --now docker
    sudo usermod -aG docker \$USER
    echo 'Docker installed. You may need to re-SSH for group changes.'
  fi

  if [ -d ~/app ]; then
    echo 'Repo already cloned, pulling latest...'
    cd ~/app && git pull
  else
    git clone '$REPO_URL' ~/app
  fi
"

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. SSH into VM:"
echo "     gcloud compute ssh $VM_NAME --zone=$ZONE"
echo ""
echo "  2. Create .env file:"
echo "     cd ~/app && nano .env"
echo "     (copy from .env.example, fill in your API keys)"
echo ""
echo "  3. Start the bot:"
echo "     cd ~/app && docker compose up -d --build"
echo ""
echo "  4. Check logs:"
echo "     docker compose logs -f --tail=20"
echo ""
