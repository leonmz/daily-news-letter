#!/usr/bin/env bash
#
# One-time GCP bootstrap for market-monitor.
#
# Architecture: Cloud Scheduler --(cron, PT)--> Cloud Run Job (`main.py --tick`)
#   * state in a GCS bucket (STATE_PATH=gs://...), Gmail App Password in Secret Manager
#   * GitHub Actions deploys via Workload Identity Federation (no SA keys)
#
# Run once with the variables below set, then push to main to deploy.
# Idempotent: safe to re-run. Review before running — it creates billable resources.
#
#   GCP_PROJECT=my-proj GCP_REGION=us-west1 GITHUB_REPO=leonmz/market-monitor \
#   EMAIL_USER=angli.claude@gmail.com EMAIL_TO=angli1937@gmail.com \
#   bash deploy/gcp_setup.sh
#
set -euo pipefail

PROJECT="${GCP_PROJECT:?set GCP_PROJECT}"
REGION="${GCP_REGION:-us-west1}"
GITHUB_REPO="${GITHUB_REPO:?set GITHUB_REPO=owner/repo}"
EMAIL_USER="${EMAIL_USER:?set EMAIL_USER}"
EMAIL_TO="${EMAIL_TO:?set EMAIL_TO}"

SERVICE="market-monitor"
AR_REPO="containers"
BUCKET="${PROJECT}-market-monitor-state"
STATE_PATH="gs://${BUCKET}/state.json"
RUNTIME_SA="mm-run@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="mm-deploy@${PROJECT}.iam.gserviceaccount.com"
SCHED_SA="mm-sched@${PROJECT}.iam.gserviceaccount.com"
POOL="github-pool"
PROVIDER="github-provider"

gcloud config set project "$PROJECT" >/dev/null

echo "== Enable APIs =="
gcloud services enable \
  run.googleapis.com cloudscheduler.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com

echo "== Artifact Registry =="
gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location "$REGION"

echo "== GCS state bucket =="
gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://${BUCKET}" --location "$REGION" --uniform-bucket-level-access

echo "== Secret: EMAIL_PASSWORD (Gmail App Password) =="
if ! gcloud secrets describe EMAIL_PASSWORD >/dev/null 2>&1; then
  read -rsp "Enter Gmail App Password for ${EMAIL_USER}: " APP_PW; echo
  printf '%s' "$APP_PW" | gcloud secrets create EMAIL_PASSWORD --data-file=-
fi

echo "== Service accounts =="
for sa in mm-run mm-deploy mm-sched; do
  gcloud iam service-accounts describe "${sa}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$sa" --display-name "market-monitor ${sa}"
done

echo "== Runtime SA: read secret + read/write state =="
gcloud secrets add-iam-policy-binding EMAIL_PASSWORD \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/storage.objectAdmin >/dev/null

echo "== First image build =="
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}:bootstrap"
gcloud builds submit --tag "$IMAGE"

echo "== Cloud Run Job =="
gcloud run jobs describe "$SERVICE" --region "$REGION" >/dev/null 2>&1 && OP=update || OP=create
gcloud run jobs "$OP" "$SERVICE" \
  --image "$IMAGE" --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --max-retries 1 --task-timeout 300 \
  --set-env-vars "^;^EMAIL_USER=${EMAIL_USER};EMAIL_FROM=${EMAIL_USER};EMAIL_TO=${EMAIL_TO};STATE_PATH=${STATE_PATH};MONITOR_TZ=America/Los_Angeles;ALERT_THRESHOLD_PCT=1.0;ALERT_THRESHOLDS=^VIX:10,^VXN:10" \
  --set-secrets "EMAIL_PASSWORD=EMAIL_PASSWORD:latest"

echo "== Cloud Scheduler: every 5 min, market hours, Pacific → run the Job =="
gcloud run jobs add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member="serviceAccount:${SCHED_SA}" --role=roles/run.invoker >/dev/null
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${SERVICE}:run"
gcloud scheduler jobs describe "${SERVICE}-tick" --location "$REGION" >/dev/null 2>&1 && SOP=update || SOP=create
gcloud scheduler jobs "$SOP" http "${SERVICE}-tick" \
  --location "$REGION" \
  --schedule "*/5 6-13 * * 1-5" \
  --time-zone "America/Los_Angeles" \
  --uri "$JOB_URI" --http-method POST \
  --oauth-service-account-email "$SCHED_SA"

echo "== Workload Identity Federation for GitHub Actions =="
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
gcloud iam workload-identity-pools describe "$POOL" --location global >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location global --display-name "GitHub pool"
gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --location global --workload-identity-pool "$POOL" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location global --workload-identity-pool "$POOL" --display-name "GitHub provider" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository=='${GITHUB_REPO}'" \
    --issuer-uri "https://token.actions.githubusercontent.com"

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_REPO}" >/dev/null

echo "== Deploy SA: build + push + roll the job =="
for role in roles/run.developer roles/cloudbuild.builds.editor roles/artifactregistry.writer \
            roles/iam.serviceAccountUser roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${DEPLOY_SA}" --role "$role" >/dev/null
done

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
cat <<EOF

✅ Bootstrap complete.

Add to GitHub repo → Settings → Secrets and variables → Actions

  Variables:
    GCP_PROJECT = ${PROJECT}
    GCP_REGION  = ${REGION}
    AR_REPO     = ${AR_REPO}

  Secrets:
    GCP_WIF_PROVIDER = ${WIF_PROVIDER}
    GCP_DEPLOY_SA    = ${DEPLOY_SA}

Then: push to main → Actions builds + rolls the job.
Test now:  gcloud run jobs execute ${SERVICE} --region ${REGION}
EOF
