# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [Semantic Versioning](https://semver.org/).

> Note: this project was built before being put under version control, so
> `0.1.0` describes everything present at the first commit rather than a
> from-scratch start. Entries describe features, not individual commits.

## [Unreleased]

## [0.1.0] — 2026-07-15

First public release.

### Added — core

- FastAPI backend (`api/main.py`) wrapping the Garmin MCP client, local storage
  and Claude services behind a REST API.
- React + Vite + ECharts frontend, replacing an earlier Streamlit app.
- **Readiness** view: HRV/sleep/Body Battery gauge with a train-or-rest verdict
  and manual weight logging.
- **Plan** view: deterministic weekly session prescriptions across a 4-week
  block, targeting your self-identified limiter, adjusted for daily readiness.
- **Overview** view: power-duration curve, FTP progression, rider phenotype,
  all-time PRs, endurance score, weight trend.
- **Trends** view: rolling HRV and readiness baselines.
- **Coach** view: Claude chat grounded in live training data, plus a
  day-analysis action.
- **History** view: activity browser with lap splits and a drag-to-select ride
  segment analyzer.
- **Builder** view: structured workout builder with `.ZWO` export.

### Added — analysis

- Coggan power profile as a continuous log-scale power-duration curve with
  category bands (Cat 5 → Pro/UCI) and a weakest-zone read.
- intervals.icu integration: PMC chart (Fitness/Fatigue/Form) styled after
  intervals.icu, with zone-coloured Form, date presets and +7d/+14d
  extrapolation.
- W/kg trajectory with **diminishing-returns forecasting** — gain rate decays
  exponentially toward a ceiling, so the model can report a plateau short of
  target rather than promising the goal eventually.
- Aerobic decoupling (first-half vs second-half Pw:Hr), gated when a ride has
  no power data.
- Time-in-zone per ride, power and heart-rate zones, from cached per-sample
  series.
- Rider phenotype classification, weakness-targeted workout suggestions, goal
  setter with progress tracking against Coggan bands.
- FTP test reminder separating "due" from "good day to test", using live Form.

### Added — data

- Persistent local JSON cache with permanent storage for past days and a
  short TTL for today.
- Firestore sync for small user-entered data (weights, FTP tests, goals,
  workouts, strength, gear, gear assignments, hidden activities). Bulky
  Garmin-derived caches deliberately stay local — Firestore caps documents at
  1MiB and a single ride's sample series can exceed 300KB.
- Rotating local backups of `local_store.json`, snapshotted before the first
  write of each day, with a restore CLI.
- Activity import from `.fit` / `.gpx` / `.tcx` files, normalised into the
  Garmin activity shape. (Live OAuth sync to Strava/Wahoo/Zwift is not built.)
- Data export: date range + category selection, JSON or CSV-per-category ZIP.
- Scheduled Garmin sync script (`scripts/sync.py`) to close PMC and
  lactate-threshold gaps on days the app isn't opened.

### Added — activities

- Route map from GPS track (no external tile provider — plotted as a shape).
- Hide-vs-delete: imported activities delete for real, Garmin activities are
  hidden locally since they refetch from source.
- Gear tracking with auto-mileage from assigned rides plus a
  default-gear-per-activity-type rule.
- Junk-activity flagging for rides that look like transfers rather than
  training (short *and* slow), flagged rather than auto-removed.
- Calendar month grid combining completed activities and planned sessions.

### Added — platform

- Firebase Auth (Google sign-in) gating the whole app, with a single allowed
  email enforced server-side.
- RSA-OAEP encryption at rest for the Anthropic key and Garmin/intervals.icu
  credentials; the private key lives outside the project.
- Redacted Mode: client-side toggle hiding fitness-revealing numbers for
  screen-sharing. Not an access-control boundary.
- Dockerfile and Cloud Run deploy scripts with Secret Manager wiring.

### Fixed

- `get_activity_details` never extracted `directLatitude`/`directLongitude`
  despite documenting them, so GPS data had never reached the frontend.
- ECharts series crash from spreading a style object over the series `type`
  field, which blanked the whole app.
- Backup restore silently recovered nothing: reads let Firestore win for synced
  keys, so a file-only restore was invisible. Restore now pushes back to
  Firestore.
- Export download button stayed disabled despite a preset appearing selected
  (`TimeRangePicker` only fires `onChange` on click, not mount).
- Export filename was lost cross-origin — `Content-Disposition` now exposed via
  CORS.
- Timezone-safe date handling; `toISOString()` shifted dates in UTC+8.
- Garmin `get_activities` rejects `limit > 100`; callers now clamp.

### Known issues

- Anything depending on activity history sees only ~the last 100 rides — Garmin's
  list tool caps there and ignores date filters.
- Without a power meter, outdoor rides have no power; decoupling and power zones
  gate themselves accordingly.
- Zone adherence compares nothing against the prescribed session — the plan
  states zones in prose, not structured targets.
