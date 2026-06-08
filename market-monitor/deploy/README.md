# Deploying market-monitor to GCP

Serverless, cron-driven. No always-on VM.

```
Cloud Scheduler  ──(*/5, 06:00–13:55 PT, Mon–Fri)──▶  Cloud Run Job: main.py --tick
        │                                                   │
        │                                       reads/writes │ state  ──▶  GCS object
        │                                       reads secret │        ──▶  Secret Manager (EMAIL_PASSWORD)
        ▼                                                    ▼
   GitHub push to main ──▶ GitHub Actions ──(WIF)──▶ Cloud Build ──▶ Artifact Registry ──▶ roll the Job
```

Each invocation runs **one tick**: the first one at/after 06:30 PT establishes the
day's baseline and emails it; later ticks email an alert only when SPY/QQQ/VIX/VXN
move past their threshold vs that baseline. The app self-gates to market hours
(ET 9:30–16:00), so the few out-of-hours scheduler fires are immediate no-ops.

Why a Cloud Run **Job** (not a Service or `--schedule`): the workload is a periodic
batch tick with no HTTP surface, and the schedule lives in Cloud Scheduler (which
handles PST/PDT for you). State is in GCS because the Job's filesystem is ephemeral.

## One-time setup

Prereqs: a GCP project with billing, `gcloud` authenticated as an owner, and a
Gmail **App Password** ready.

```bash
GCP_PROJECT=your-proj \
GCP_REGION=us-west1 \
GITHUB_REPO=leonmz/market-monitor \
EMAIL_USER=angli.claude@gmail.com \
EMAIL_TO=angli1937@gmail.com \
bash deploy/gcp_setup.sh
```

It enables APIs and creates: Artifact Registry repo, GCS state bucket, the
`EMAIL_PASSWORD` secret (prompted), runtime/deploy/scheduler service accounts +
IAM, the first image, the Cloud Run Job, the Cloud Scheduler job, and the
Workload Identity Federation pool/provider for GitHub Actions. It prints the
GitHub **Variables** and **Secrets** to paste into the repo settings.

## Auto-deploy

After the variables/secrets are set, every push to `main`:
1. runs `ruff` + `pytest` (the `test` job),
2. builds the image via Cloud Build → Artifact Registry,
3. `gcloud run jobs update` rolls the Job to the new image.

Trigger a run by hand anytime: **Actions → Deploy to GCP → Run workflow**.

## Verify / operate

```bash
gcloud run jobs execute market-monitor --region us-west1   # run a tick now
gcloud run jobs executions list --job market-monitor --region us-west1
gcloud scheduler jobs describe market-monitor-tick --location us-west1
gcloud storage cat gs://<PROJECT>-market-monitor-state/state.json   # current baseline/refs
```

Tune thresholds without a redeploy:
```bash
gcloud run jobs update market-monitor --region us-west1 \
  --update-env-vars '^;^ALERT_THRESHOLDS=^VIX:15,^VXN:15'   # ;-delimited: comma stays literal
```

## Notes

- **SMTP egress:** Cloud Run blocks port 25 but allows 587/465, so Gmail SMTP works.
- **Cost:** a tick is a few seconds; ~150 executions/trading day on the free-ish
  tier → effectively cents/month. Cloud Scheduler's first 3 jobs are free.
- **Rotate the App Password:** `gcloud secrets versions add EMAIL_PASSWORD --data-file=-`.
- **Alternative (not covered here):** a single Compute Engine `e2-micro` running
  `python main.py --schedule` under systemd, with local-file state — simpler, but
  an always-on VM. The Dockerfile + image work there too.
