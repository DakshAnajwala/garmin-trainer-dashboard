#!/bin/bash
# One-time setup: uploads the local secrets Cloud Run needs into Secret
# Manager. Run this once (or again if you ever rotate a key). Requires
# `gcloud auth login` + `gcloud config set project YOUR_PROJECT_ID` first.
#
# Why these 4 and not the plaintext values directly as env vars: the RSA
# private key decrypts config/secrets.py's ciphertext (Anthropic/Garmin/
# intervals.icu keys) and the Firebase service account key grants backend
# admin access — both are too sensitive for plain env vars (visible in
# `gcloud run services describe` output, deploy logs, etc). Secret Manager
# keeps them out of that surface and access-controlled separately.
set -euo pipefail
cd "$(dirname "$0")/.."

create_or_update_secret() {
  local name="$1" file="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    gcloud secrets versions add "$name" --data-file="$file"
  else
    gcloud secrets create "$name" --data-file="$file" --replication-policy=automatic
  fi
}

create_or_update_secret rsa-private-key "$HOME/.garmin-trainer-dashboard/keys/private_key.pem"
create_or_update_secret rsa-public-key "$HOME/.garmin-trainer-dashboard/keys/public_key.pem"
create_or_update_secret secrets-enc-json "data/secrets.enc.json"
create_or_update_secret firebase-credentials-json "$HOME/.garmin-trainer-dashboard/keys/firebase-credentials.json"

echo "Done. 4 secrets are in Secret Manager: rsa-private-key, rsa-public-key, secrets-enc-json, firebase-credentials-json."
