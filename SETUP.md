# Setup guide

Get your own copy running. Roughly 20–30 minutes, most of it clicking through
the Firebase console.

**You bring your own accounts and keys.** Nothing in this repo is pre-configured
with anyone's credentials — you'll need a Garmin account, an Anthropic API key,
and a free Firebase project.

---

## What you need first

| Thing | Why | Cost |
|---|---|---|
| **Garmin Connect account** | The data source. A watch or head unit that syncs to it. | — |
| **Python 3.11+** | Backend | Free |
| **Node.js 20+** | Frontend, and the Garmin MCP server | Free |
| **Anthropic API key** | The AI coach ([console.anthropic.com](https://console.anthropic.com)) | Pay-per-use, cents per chat |
| **Firebase project** | Login + cloud sync | Free tier is plenty |
| **intervals.icu account** *(optional)* | Fitness/Fatigue/Form chart | Free |

Without an Anthropic key everything works except the Coach tab. Without
intervals.icu everything works except the PMC chart.

---

## 1. Clone and install

```bash
git clone https://github.com/DakshAnajwala/garmin-trainer-dashboard-public.git
cd garmin-trainer-dashboard-public

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd frontend && npm install && cd ..
```

## 2. Firebase project

The app is single-user by design: you sign in with Google, and the backend only
accepts *your* email.

**Create the project**
1. [console.firebase.google.com](https://console.firebase.google.com) → **Create a project**
2. Name it whatever you like. Google Analytics is not needed — skip it.

**Enable Google sign-in**
3. **Build → Authentication → Get started**
4. **Sign-in method** tab → **Google** → enable → pick a support email → Save

**Enable Firestore**
5. **Build → Firestore Database → Create database**
6. Choose **Production mode**. Pick any region.

**Get the web config** (for the frontend)
7. ⚙️ gear icon → **Project settings** → **General** tab
8. Scroll to **Your apps** → click the `</>` (web) icon → register an app
9. Copy the `firebaseConfig` values — you'll paste them in step 4.

**Get the service-account key** (for the backend)
10. **Project settings** → **Service accounts** tab → **Generate new private key**
11. A JSON file downloads. **Move it outside this repo**, e.g.:
    ```bash
    mkdir -p ~/.garmin-trainer-dashboard/keys
    mv ~/Downloads/your-project-firebase-adminsdk-*.json ~/.garmin-trainer-dashboard/keys/firebase-credentials.json
    chmod 600 ~/.garmin-trainer-dashboard/keys/firebase-credentials.json
    ```
    This file grants admin access to your Firebase project. Never commit it.

## 3. Your profile

```bash
cp config/athlete_profile.example.json config/athlete_profile.json
```

Open it and replace **every** value with your own: power curve, FTP test
history, max HR, LTHR, and the `coach_context` block describing your goals and
schedule.

This file is gitignored — your physiology stays on your machine.

> The app boots on the example values so you can look around first, but they're
> placeholders. Every W/kg number, training zone and coaching answer is wrong
> until you put your real numbers in.

The `coach_context` field is worth real effort — it's free text injected into
the AI coach's prompt, and it's the difference between generic advice and
advice that knows you gained weight on purpose or that Saturday's group ride is
non-negotiable.

## 4. Environment files

**Backend:**
```bash
cp .env.example .env
```
Edit it: set `FIREBASE_CREDENTIALS_PATH` to where you moved the JSON,
`ALLOWED_EMAIL` to your Google account, and `TARGET_WKG` to your goal.

**Frontend:**
```bash
cp frontend/.env.example frontend/.env.local
```
Paste in the `firebaseConfig` values from step 2.9.

## 5. Credentials

```bash
python -m scripts.set_secrets
```

Prompts for your Anthropic API key, Garmin email/password, and intervals.icu API
key (Settings → Developer Settings on intervals.icu). Press Enter to skip any.

Input is hidden and never echoed. Values are encrypted with RSA-OAEP; only
ciphertext is written to `data/`, and the private key is generated into
`~/.garmin-trainer-dashboard/keys/` — outside the repo, so leaking the project
folder doesn't leak your credentials.

To change a key later, just run it again.

## 6. Run it

```bash
./start.sh
```

Backend on `:8000`, frontend on `:5173`. Ctrl+C stops both. Open
http://localhost:5173 and sign in with the Google account you set as
`ALLOWED_EMAIL`.

First load is slow — it's fetching from Garmin. After that it's cached.

---

## Optional

### Daily sync

Data only refreshes when you open the app, which leaves gaps: Garmin's
lactate-threshold endpoint returns only a *current* value with no history, so a
change on a day you never opened the dashboard is lost permanently.

```bash
python -m scripts.sync            # run manually
```

Cron it (6am daily):
```bash
crontab -e
# then add:
0 6 * * * cd /full/path/to/repo && .venv/bin/python -m scripts.sync >> /tmp/garmin-sync.log 2>&1
```

### Backups

A snapshot of your data is taken automatically before the first write of each
day, into `~/.garmin-trainer-dashboard/backups/` (30 days retained).

```bash
python -m scripts.backups                      # list
python -m scripts.backups --restore 2026-07-15 # restore
```

### Deploy to Cloud Run

Makes it reachable from your phone. Needs the `gcloud` CLI and a billing account
(Cloud Run and Firestore free tiers cover single-user use, but Google requires a
card on file — set a budget alert).

```bash
gcloud auth login
gcloud config set project YOUR_FIREBASE_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

cp deploy/env.example.yaml deploy/env.yaml   # edit with your values
./deploy/setup-secrets.sh                    # uploads keys to Secret Manager
./deploy/deploy.sh
```

Then add the resulting `*.run.app` domain to Firebase console → Authentication →
Settings → **Authorized domains**, or Google sign-in will reject it.

---

## Troubleshooting

**"Firebase isn't configured"** — `frontend/.env.local` is missing or empty.
Vite only reads env at startup; restart the dev server after editing it.

**401 "Missing bearer token"** on API calls — expected when not signed in. If it
persists after signing in, your `ALLOWED_EMAIL` doesn't match the account you
used.

**"Anthropic rejected the stored API key"** — bad or expired key. Re-run
`python -m scripts.set_secrets`, then restart the backend.

**Changes to `.env` seem ignored** — it's read once at startup. Restart the
backend. `--reload` only watches Python files.

**Garmin fetch fails / hangs** — the MCP server is `npx`-launched on first use
and can be slow initially. Check your credentials with
`python -m garmin_mcp.garmin_client --call get_activities`.

**No power data on outdoor rides** — expected without a power meter. Metrics
that need power (decoupling, power zones) gate themselves and say so.

---

## Known limitations

- Garmin's activity list **caps at 100 and ignores date filters**, so anything
  built on activity history only sees roughly your last 100 rides. Gear mileage
  undercounts for older equipment; there's a manual "starting km" field for that.
- **Firestore documents cap at 1MiB**, so only small user-entered data syncs
  (weights, goals, gear, FTP tests). GPS tracks and per-sample series stay local
  — they'd blow the cap within a handful of rides.
- **Redacted Mode is a display toggle, not access control.** It hides numbers in
  the UI; anyone with API access still sees everything.
- Cycling only. Single user. No multi-athlete or social features.
