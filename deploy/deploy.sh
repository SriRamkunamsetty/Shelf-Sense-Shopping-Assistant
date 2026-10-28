#!/usr/bin/env bash
# Usage: PROJECT_ID=my-proj ./deploy/deploy.sh [--demo]
#   --demo  enables the demo helpers (simulate shoppers / reset) — use for judging, never for real customers.
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
DEMO=false; SEED=false; [[ "${1:-}" == "--demo" ]] && { DEMO=true; SEED=true; }
gcloud builds submit --project "$PROJECT_ID" --config cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_DEMO=${DEMO},_SEED=${SEED}"
gcloud run services describe shelfsense --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)'
