#!/usr/bin/env bash
# One-time project setup. Usage: PROJECT_ID=my-proj REGION=asia-south1 ./deploy/setup_gcp.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SA="shelfsense-run@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  firestore.googleapis.com aiplatform.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com

gcloud artifacts repositories describe shelfsense --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create shelfsense --repository-format=docker --location="$REGION"

gcloud firestore databases describe >/dev/null 2>&1 || \
  gcloud firestore databases create --location="$REGION" --type=firestore-native

gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create shelfsense-run --display-name="ShelfSense Cloud Run runtime"

# Least privilege: only what the app uses.
for role in roles/datastore.user roles/aiplatform.user roles/bigquery.dataEditor roles/bigquery.jobUser roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role="$role" --condition=None >/dev/null
done

# Owner-console key (shown once; store it in your password manager).
if ! gcloud secrets describe shelfsense-ops-key >/dev/null 2>&1; then
  KEY="$(openssl rand -base64 24)"
  printf '%s' "$KEY" | gcloud secrets create shelfsense-ops-key --data-file=-
  echo "OPS_API_KEY (enter this in the Owner console): $KEY"
fi
echo "Setup complete. Deploy with ./deploy/deploy.sh"
