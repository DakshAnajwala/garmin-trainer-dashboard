# Garmin Trainer Dashboard

A self-hosted cycling training dashboard. Pulls your Garmin Connect data via
MCP, combines it with intervals.icu fitness metrics and a Claude-powered coach,
and tracks progress toward a dynamic W/kg goal (target watts = your goal W/kg x
your *current* weight, so it moves with you).

Single-user by design — one allowed Google account, no multi-tenancy, no social
features. Cycling only. **Bring your own API keys**: nothing here is
pre-configured with anyone's credentials.

**→ [SETUP.md](SETUP.md) to get it running.**

## Stack

| Layer | What |
|---|---|
| Backend | FastAPI (`api/main.py`), Python 3.13 |
| Frontend | React + Vite + ECharts (`frontend/`) |
| Data | Garmin Connect via MCP, intervals.icu REST |
| Storage | Local JSON cache + Firestore for user-entered data |
| Auth | Firebase Auth (Google sign-in), single allowed email |
| AI | Anthropic Claude (day analysis, ride analysis, chat) |

## Running it

```bash
./start.sh          # backend :8000 + frontend :5173, Ctrl+C stops both
```

Or separately:

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
cd frontend && npm run dev
```

## Setup

See **[SETUP.md](SETUP.md)** for the full walkthrough.

In short: create a Firebase project, `cp .env.example .env`,
`cp frontend/.env.example frontend/.env.local`,
`cp config/athlete_profile.example.json config/athlete_profile.json`, then
`python -m scripts.set_secrets` for your Anthropic/Garmin/intervals.icu
credentials.

Secrets are encrypted at rest (RSA-OAEP): only ciphertext is written to `data/`,
and the private key is generated outside the repo in
`~/.garmin-trainer-dashboard/keys/`. Your physiology lives in
`config/athlete_profile.json`, which is gitignored.

## Scripts

| Command | Purpose |
|---|---|
| `python -m scripts.set_secrets` | Store/rotate encrypted credentials |
| `python -m scripts.sync` | Pull Garmin data into the cache (cron this daily) |
| `python -m scripts.backups` | List local_store backups |
| `python -m scripts.backups --restore YYYY-MM-DD` | Restore a backup |
| `./deploy/setup-secrets.sh` | Upload secrets to Google Secret Manager (one-time) |
| `./deploy/deploy.sh` | Deploy to Cloud Run |

## Features

**Readiness** — HRV/sleep/Body Battery gauge with a train-or-rest verdict.
**Plan** — weekly session prescriptions across a 4-week block, readiness-adjusted.
**Calendar** — month grid of completed activities + planned sessions.
**Overview** — power curve, FTP progression, Coggan profile, W/kg trajectory with
diminishing-returns forecasting, goals.
**Trends** — rolling HRV/readiness baselines, intervals.icu PMC (Fitness/Fatigue/Form).
**History** — activity browser with route map, time-in-zone, lap splits, segment
selector, AI ride analysis, aerobic decoupling.
**Builder** — structured workout builder with .ZWO export.
**Aero** — position/equipment profile (framework).
**Gear** — equipment tracking with auto-mileage from assigned rides.
**Coach** — Claude chat grounded in live training data.

**Redacted Mode** hides fitness-revealing numbers for screen-sharing. It's a
client-side display toggle, not an access-control boundary.

## Notes / limitations

- Garmin's activity list caps at 100 and ignores date filters, so anything
  depending on activity history only sees roughly the last 100 rides.
- Without a power meter, outdoor rides have no power data; metrics that need it
  (aerobic decoupling, power zones) gate themselves and say so rather than
  guessing.
- Firestore documents cap at 1MiB, so only small user-entered data syncs there.
  GPS tracks, per-sample series and parsed imports stay local-only.
- Reference numbers (Coggan category bands, training zones) are the widely
  reproduced community figures, not independently derived. Treat as directional.
