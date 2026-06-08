# market-monitor — container image for a Cloud Run Job (one tick per invocation).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
# google-cloud-storage backs STATE_PATH=gs://... (Cloud Run's filesystem is
# ephemeral between scheduled invocations, so state lives in GCS).
RUN pip install --no-cache-dir -r requirements.txt google-cloud-storage

COPY monitor ./monitor
COPY main.py .

# Cloud Scheduler triggers the Job on a cron; each run performs one tick
# (establish the day's baseline if needed, otherwise alert on >threshold moves).
ENTRYPOINT ["python", "main.py"]
CMD ["--tick"]
