# Garmin Trainer Dashboard — AI Context Brief

This document gives another AI enough context to reason about this codebase as a
**hackathon submission for a "Good Health and Well-Being" track**, without needing
to read the whole repo. It describes what the app does, why it's a fit for the
theme, its architecture, and what's real vs. what would need to be reframed/extended
for a pitch.

## One-line pitch

A personal cycling training platform that turns raw wearable data (Garmin) into
**daily, explainable, physiology-aware guidance** — "should I train hard today or
rest," "what workout should I do and why," "am I overreaching" — instead of just
displaying charts. It improves *access to awareness* of physical health by closing
the loop between passive data collection (a watch/HR strap already tracking you)
and an actual daily decision a person can act on.

## Why it fits "Good Health and Well-Being"

Most fitness wearables collect enormous amounts of physiological data (HRV, resting
HR, training load, power output) that never turns into a decision the user
understands. This project's core thesis: **awareness only matters if it's
legible and acted on.** Concretely:

- **Readiness score** (`services/readiness.py`) fuses HRV trend, sleep, resting HR,
  and recent training load into a single daily readiness verdict with a plain-language
  explanation — the kind of thing usually locked inside a paid platform, made
  transparent and locally owned instead.
- **Every recommendation is preview-then-confirm, never a silent auto-decision.**
  This is a deliberate, repeated design rule across the whole app (readiness advisory,
  plan reflow, AI-planned workouts): the system shows *why* before it acts, treating
  the user as the decision-maker, not the system.
- **Deterministic-first, AI-second architecture.** Every AI-touched feature has a
  non-AI fallback that still works if the AI call fails or the key is missing — health
  guidance shouldn't go dark because of an API outage. This also means the "awareness"
  layer is explainable by inspection, not just an LLM's opinion.
- **Overreaching / burnout guardrails**, not just performance-chasing: the plan
  logic actively avoids stacking hard sessions, flags bad placement of hard workouts
  next to rest days, and never silently escalates load.
- Mental-health-adjacent angle available: HRV and readiness are established proxies
  for stress/recovery, not just sport performance — this is defensible as a
  physical **and** early-signal wellbeing tool, not purely a performance app.

If pitching, the honest framing is: **"a low-cost, always-available layer of
physiological self-awareness that sits on top of data most wearable owners already
have, but currently can't interpret."**

## Architecture at a glance

- **Backend**: Python/FastAPI (`api/main.py`), single-user, Firebase-authenticated.
- **Frontend**: React + Vite (`frontend/`), tabbed SPA.
- **Data ingestion**: Garmin Connect via `garmin_mcp/garmin_client.py` (an MCP-based
  client), plus manual import of Strava/Wahoo/Zwift files, plus optional
  intervals.icu sync (`services/intervals_icu.py`).
- **Storage**: local JSON store (`database/local_store.py`) as source of truth,
  selectively synced to Firestore under a `_SYNCED_KEYS` allowlist (Firestore's
  1 MiB/doc cap is a real constraint here — only small, high-value keys sync).
- **AI**: Anthropic Claude, used narrowly and always as an *enrichment* layer on
  top of deterministic logic (never the sole source of a health-relevant decision).
  `services/claude_analyzer.py` is the shared call wrapper; failures degrade to
  deterministic output with a clear "AI unavailable" message, never a crash or a
  silently wrong answer.
- **Secrets**: encrypted local secret store (`config/secrets.py`,
  `services/app_settings.py`) — API responses only ever report "configured /
  not configured," never the secret value itself. Garmin credentials are
  intentionally CLI-only, never settable through a web form (smaller attack
  surface for a third-party account password).

## Feature inventory (what's actually built)

**Physical readiness & recovery**
- `services/readiness.py` — daily readiness score from HRV/sleep/RHR/training load.
- `services/physiology_model.py` — modeled CP (critical power), W′, durability,
  repeatability from ride data.
- `services/adaptive_load.py` / `adaptive_periodization.py` — training-load-aware
  periodization and overreach detection.

**Training planning & guidance**
- `services/plan_generator.py`, `plan_reflow.py` — generates/rebalances a week of
  planned sessions around missed workouts, without destroying athlete edits.
- `services/day_planner.py` + `ai_day_planner.py` + `services/workout_types.py` —
  the newest feature: click a calendar day, get a menu (build your own / pick from
  library / **"let my coach plan for me"** / generate the week). The coach option
  picks a workout **type** (VO2max, lactate threshold, overgearing, anaerobic,
  endurance) from the athlete's weakest measured zone or an upcoming race's demand
  gap, checks it isn't stacked next to another hard day, and only then lets an
  optional AI layer add a warmer rationale — all preview-then-confirm.
- `services/training_plan.py`, `route_demand.py` — race-specific demand modeling
  (what does this course require vs. what can this athlete currently do).

**Performance analysis (the "data → understanding" layer)**
- `services/coggan.py`, `power_curve.py` — Coggan power-profile chart, mean-max
  power curve, weakest-zone detection.
- `services/ftp.py`, `ftp_test.py` — FTP estimation and test-reminder logic.
- `services/ride_analysis.py`, `activity_quality.py`, `personal_records.py`,
  `trajectory.py` — per-ride debriefs, PR detection, long-term trajectory.
- `services/custom_model.py`, `model_backtest.py` — lets the athlete define/test
  their own scoring formula against historical data (transparency over black-box).

**AI coaching surface**
- `/api/coach/chat` (+ streaming variant) — conversational coach grounded in the
  athlete's real stored data (`services/data_query.py` answers structured questions
  the chat can call into), not a generic chatbot.
- `services/brief.py` — daily "morning brief" summarizing readiness + plan + notable
  changes.

**Supporting infrastructure**
- Gear tracking/auto-attribution (`services/gear.py`), workout export to `.ZWO`
  (Zwift) format, calendar UI, settings/athlete profile split, undo log for
  destructive actions, CSV/JSON export of all data.

## Design principles worth citing in a pitch

1. **Deterministic-first, AI-enrichment-second** — the app never depends on an LLM
   being available or correct for a health-relevant decision to be usable.
2. **Preview, don't auto-act** — every recommendation is shown with its reasoning
   and requires explicit confirmation before it changes the athlete's plan.
3. **Explainability over black-box scores** — readiness, plan choices, and workout
   picks all carry a human-readable "why," and the custom-algo feature lets the
   athlete inspect/replace the scoring logic itself.
4. **Safety rails are hard constraints, not suggestions** — e.g. a configured
   floor body weight the coach will never recommend going under; a non-negotiable
   fixed weekly commitment the planner will never schedule over.
5. **Single-user, privacy-conscious by construction** — local-first storage, secrets
   never echoed back through the API, third-party credentials kept out of the web
   surface entirely.

## What's NOT built / honest gaps for a hackathon pitch

- Single-athlete only — no multi-user accounts, no social/community layer.
- No mental-health-specific instrumentation (mood logging, stress journaling) —
  the wellbeing angle currently rides entirely on HRV/readiness as a physiological
  proxy, not a self-reported one. Adding a simple daily mood/stress check-in that
  feeds the same readiness engine would strengthen the "mental health" half of the
  track considerably and is a natural, scoped extension.
- Cycling-specific — the physiology models (FTP, power curves, w/kg) don't
  generalize to other sports/activities without rework.
- No onboarding flow for a new user — the whole app currently assumes one
  pre-configured athlete's data is already flowing in from Garmin.
