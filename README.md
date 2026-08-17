# Praxis

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

## Security & privacy

This app holds personal health data and uses your real Garmin credentials.
**→ [SECURITY.md](SECURITY.md)** covers the threat model in full. The short
version:

- **Bring your own keys** — nothing here is pre-configured with anyone's
  credentials, and none are committed.
- **Encrypted at rest** — RSA-OAEP; ciphertext in `data/`, private key outside
  the repo at `~/.garmin-trainer-dashboard/keys/` (`0600`).
- **CLI-only credential entry** — no web form or endpoint accepts a Garmin
  password, deliberately. Please don't add one.
- **Auth fails closed** — every route needs a valid Firebase token *and* a
  matching `ALLOWED_EMAIL`. Unconfigured Firebase returns `503`, it does not
  serve your data unauthenticated.
- **Your Garmin password reaches a third-party npm package**
  (`@nicolasvegam/garmin-connect-mcp`), which performs the actual login. Garmin
  offers no official API or OAuth for this data. Review/pin it if that matters
  to you.

If you fork this, check `data/` is ignored before your first commit — it holds
your GPS tracks, and ride start points reveal home addresses.

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

**Readiness** — HRV/sleep/Body Battery gauge with a train-or-rest verdict, a
morning brief, and weight/W-kg logging.
**Plan** — weekly session projection across a 4-week block, readiness-adjusted,
with block-phase and week-reflow advisories and 300 km/week compliance tracking.
**Calendar** — month grid of completed activities + planned sessions, with an
intervals.icu-style *Add Calendar Entry* picker and a **"What should I do
today?"** panel offering three options you can add individually.
**Power** — power-duration curve, FTP progression, Coggan profile, W/kg
trajectory with diminishing-returns forecasting, goals.
**Trends** — rolling HRV/readiness baselines, intervals.icu PMC
(Fitness/Fatigue/Form), and plain-English queries over your own history.
**History** — activity browser with route map, time-in-zone, lap splits, segment
selector, AI ride analysis, aerobic decoupling.
**Builder** — structured workout builder with `.ZWO` export.
**Athlete** — rider phenotype, physiology model (CP/W′/durability), aero and
gear profiles, data export.
**Race** — target events with GPX course-demand modelling and a gap report
against your current profile.
**Coach** — Claude chat grounded in live training data, streaming replies.

### How planning works

Nothing lands on your calendar without you confirming it. Every recommendation
is preview-then-confirm, and shows *why* it picked what it picked.

Workout **type** is chosen deterministically — from your weakest Coggan zone,
a race's demand gap, and the week's existing load — with no AI call, so it keeps
working when the Anthropic key is missing or invalid. The AI layer only re-ranks
that choice within the same fixed catalog and rewrites the rationale in a
warmer voice; if it fails for any reason, the deterministic pick stands
untouched. Strength recommendations are keyed off the same weakness signal.

**Redacted Mode** hides fitness-revealing numbers for screen-sharing. It's a
client-side display toggle, not an access-control boundary — see
[SECURITY.md](SECURITY.md).

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
