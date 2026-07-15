#!/bin/bash
# Deploys to Cloud Run. Uploads the local source, builds the Dockerfile
# remotely via Cloud Build (no local Docker needed), and deploys.
#
# --allow-unauthenticated makes the Cloud Run *network endpoint* public —
# that's what makes "check it from your phone anywhere" possible. It does
# NOT bypass app-level security: every request still needs a valid Firebase
# token for your allowed account (see auth/firebase_auth.py), enforced
# inside the app regardless of who can reach the URL.
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="us-central1"
SERVICE="garmin-trainer-dashboard"

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2 \
  --env-vars-file deploy/env.yaml \
  --set-secrets="/root/.garmin-trainer-dashboard/keys/private_key.pem=rsa-private-key:latest,/root/.garmin-trainer-dashboard/keys/public_key.pem=rsa-public-key:latest,/app/data/secrets.enc.json=secrets-enc-json:latest,/secrets/firebase-credentials.json=firebase-credentials-json:latest"

echo ""
echo "Deployed. Copy the Service URL above and:"
echo "  1. Add its domain to Firebase Console > Authentication > Settings > Authorized domains"
echo "  2. Open it and sign in with your allowed account"
