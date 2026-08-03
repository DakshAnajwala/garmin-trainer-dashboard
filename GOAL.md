# Session goal (started 2026-08-03)

Self-paced development session. This file is the spec + log: what's planned,
what's in progress, what's done. Inspectable at any point, not just at the end.

## Ground rules

- Checkpoint commits as logical chunks finish — not one giant uncommitted diff.
- Never touch the Saturday team ride rule (non-negotiable, advise-only).
- Any UI change gets a `vite build` at minimum; browser-verify with screenshots
  when the Chrome extension is available.
- New backend logic touching athlete data (distance, power, FTP) reuses the
  existing dedup/exclusion helpers instead of re-deriving them —
  `services/data_query.py` and `services/power_curve.py` already paid for those
  bugs once (see the "distance in june" triple-count fix).
- Redacted Mode: any new tile showing power/FTP/TSS/HRV/weight/W-kg must respect
  `useRedact()`. Plain distance/RPE/HR-adjacent stuff doesn't need to hide.
- **Nothing lands on the calendar without the athlete confirming it.** Standing
  rule across this app (readiness advisory, adaptive periodization, plan reflow,
  coach-plan): show the reasoning, let the athlete approve or override.

---

# FEATURE SPEC: intervals.icu-style calendar + "What should I do today?"

Requested 2026-08-03. Four things in one feature:

1. Clicking a calendar day opens a **categorised Add Calendar Entry modal**
   (the intervals.icu picker in the reference screenshot), not the current
   four-button inline strip.
2. **Training plans are only generated when explicitly asked for** — no
   auto-materialising a week.
3. **"What should I do today?" returns exactly 3 suggestions**, each
   individually addable to the calendar, each with an "ask about this" follow-up.
4. Intervals are chosen from **power-curve weaknesses via explicit if/else
   rules**, and **strength training gets its own weakness-driven
   recommendation** alongside the bike session.

## 0. What already exists (reuse, do not rebuild)

Substantial parts of this are already built. Getting this wrong means
duplicating a working subsystem, so the audit matters.

| Thing | Where | State |
|---|---|---|
| Dated planned-workout store | `database/local_store.py` → `get_planned_workouts` / `save_planned_workout` / `delete_planned_workout`, with undo | Working |
| Planned-workout API | `api/main.py` → `GET/PUT/DELETE /api/planned[/{date}]` | Working |
| Month calendar grid + day detail | `frontend/src/views/CalendarView.jsx` | Working |
| Per-day edit modal w/ step editor | `frontend/src/components/PlannedWorkoutModal.jsx` | Working |
| Workout type catalog → structured steps | `services/workout_types.py`, 5 types, `build(type, ftp, intensity)` | Working |
| Weakness → type decision | `services/day_planner.py` → `decide_type()` | Working, needs extending |
| Placement/spacing warnings | `services/day_planner.py` → `check_placement()` | Working |
| AI re-rank + rationale prose | `services/ai_day_planner.py` → `enrich()` | Working, degrades gracefully |
| Single-suggestion preview/confirm | `frontend/src/components/CoachPlanModal.jsx` + `POST /api/planned/{date}/coach-plan` | Working — **this is the 1-option ancestor of the 3-option flow** |
| Coggan profile + weakest zone | `services/coggan.py` → `build_profile()` | Working |
| Strength session logging (past) | `local_store.strength_sessions`, `/api/strength`, `StrengthLog.jsx` | Working — **log only, no planning** |
| Chat / streaming chat | `api.chat()`, `api.chatStream()` | Working |
| Travel windows | `ConstraintsPanel.jsx`, constraints store | Working — **not shown on calendar** |

### The five real gaps

1. **Day menu is a flat 4-button strip**, not a categorised picker, and offers
   no strength / rest / note / sick / travel entry at all.
2. **Suggestions are 1-at-a-time.** `coach-plan` returns a single workout. The
   ask is 3 parallel options with distinct rationales.
3. **Strength is log-only.** There is no way to *plan* a strength session, and
   no logic anywhere that recommends *what kind* of strength work to do.
4. **`WORKOUT_TYPES` has no neuromuscular/sprint prescription.** When the
   weakest zone is Neuromuscular, `decide_type()` silently falls back to
   `anaerobic` and admits it in the reason string. For a feature whose whole
   premise is "intervals based on power-curve weaknesses", the most common
   weakness for a Cat 3/4 sprinter-ish rider having no dedicated prescription
   is the biggest hole in the logic.
5. **The Plan tab auto-generates.** `PlanView.jsx` calls `api.weekPlan()` /
   `api.todayPlan()` on mount, which builds a template week unprompted. The
   Calendar is already correctly opt-in ("Generate this week" is a button, and
   the empty state says *"Nothing is planned until you choose to"*). These two
   tabs contradict each other on the exact point requirement #2 is about.

## 1. Data model changes

### 1.1 New `session_type` values on planned workouts

`PlannedWorkoutModel.session_type` is a free string today; the enumerated set
lives in two places that must both be updated:

- `frontend/src/components/PlannedWorkoutModal.jsx` → `SESSION_TYPES`
- `frontend/src/views/CalendarView.jsx` → `PLANNED_COLOR`

Add: `strength`, `note`, `sick`, `travel_day`. Keep existing `rest`,
`endurance`, `intervals`, `long_ride`, `team_ride`, `custom`.

Colour assignments (reuse existing CSS vars, no new palette):

| session_type | var | rationale |
|---|---|---|
| `strength` | `--serious` / purple-ish | distinct modality, must not read as a bike session |
| `note` | `--text-muted` | informational, lowest visual weight |
| `sick` | `--critical` | it's a flag, it should look like one |
| `travel_day` | `--text-muted`, dashed border | constraint not a session |

### 1.2 Planned strength vs logged strength — keep both, don't merge

Deliberate decision: a **planned** strength session goes into
`planned_workouts` with `session_type: "strength"` and empty `steps`. A
**completed** strength session stays in `strength_sessions` via `/api/strength`.

Why not one store: `planned_workouts` is one-entry-per-day and already
calendar-rendered, undo-able, and editable — a planned strength session gets
all of that for free. `strength_sessions` is a many-per-day historical log
feeding trends. Merging them would force one to grow the other's constraints.

Consequence to handle: a planned strength day should offer a **"mark as done"**
action that writes a `strength_sessions` entry (prefilled from the plan's
focus + duration) rather than making the athlete re-enter it. This is the one
place the two stores talk.

### 1.3 Travel windows rendered on the calendar

`ConstraintsPanel`'s travel windows already exist and already override the plan
for those days, but are invisible on the Calendar. Fetch constraints in
`CalendarView` and render an ✈️ marker on any day inside a window. The "Travel"
option in the new modal writes to **that existing store** — do not create a
second parallel travel concept.

## 2. The weakness → workout if/else rules

This is the core of the request. All rules are **deterministic, no AI**, living
in `services/day_planner.py`, matching the existing `_COGGAN_ROW_TO_TYPE` style.

### 2.1 The input signal

`services/coggan.py::build_profile()` returns `weakest_zone` — the label of the
row whose category rank is lowest. Exact label strings (match by **prefix**,
they carry parenthetical caveats):

| Coggan duration | `weakest_zone` label (exact) |
|---|---|
| 5s | `Neuromuscular (~15s; Coggan reference is 5s)` |
| 60s | `Anaerobic Capacity (1min)` |
| 300s | `VO2max (5min; self-reported as not a max effort)` |
| 1200s | `Functional Threshold (current FTP; Coggan reference is 20min)` |

Categories: `Cat 5 → Cat 4 → Cat 3 → Cat 2 → Cat 1 → Pro/UCI`, plus
`Below Cat 5` which ranks *lowest* (it's not in `CATEGORIES`, so `_rank()`
returns -1 — this is correct and load-bearing; don't "fix" it).

⚠️ **Known data caveat to surface in the UI, not silently model around:** the
5min row is self-reported as *not a maximal effort*, and the 20min row reads
from FTP rather than a measured 20min. So "VO2max is your weakest zone" may be
an artefact of never having tested it maximally. Any suggestion keyed off the
VO2max row must say so in its reason string.

### 2.2 Rule A — weakest zone → cycling workout type

Extends the existing `_COGGAN_ROW_TO_TYPE` map. **New: add a `neuromuscular`
type to `services/workout_types.py`** so the Neuromuscular row stops falling
back to `anaerobic`.

```
if weakest starts with "Neuromuscular"        → neuromuscular   (NEW TYPE)
elif weakest starts with "Anaerobic Capacity" → anaerobic
elif weakest starts with "VO2max"             → vo2max
elif weakest starts with "Functional Threshold" → lactate_threshold
else                                          → endurance   (no signal yet)
```

The new `neuromuscular` template (mirroring the existing generator shape:
`_interval_steps`, %FTP + cadence, 0..1 intensity knob):

- 10min warmup
- `8-12 x 10-15s` maximal-effort sprints at **150-200% FTP**, cadence 100-120rpm
- **4-5min full recovery** between reps (this is the defining feature — short
  recoveries turn it into an anaerobic session, which is a *different* row)
- 10min cooldown
- Detail text must state target watts from FTP, and note that a true sprint is
  effort-limited not watt-limited — the number is a floor, not a ceiling.

### 2.3 Rule B — the three-option composition

The endpoint returns **exactly 3**. Composition is itself an if/else, evaluated
in order. Day-of-week and readiness gates come **first** because they can
invalidate the whole premise of a hard suggestion.

```
# --- Gate 0: the week's fixed structure (from athlete profile) ---
if weekday == SATURDAY:
    Option 1 = "Team ride (non-negotiable)" — NOT replaceable, effort-management
               advice only. Never offer to swap it out.
    Option 2 = strength focus, downgraded (see Rule C modifiers)
    Option 3 = "Add a note / log RPE for the team ride"
elif weekday == MONDAY:
    Option 1 = "Full rest" (the profile's fixed rest day)
    Option 2 = mobility/core-only strength
    Option 3 = the weakness-targeted session, clearly labelled
               "if you want to move your rest day"

# --- Gate 1: readiness ---
elif readiness verdict in (REST, EASY):
    Option 1 = recovery spin or full rest, quoting the readiness reason
    Option 2 = mobility/core strength only
    Option 3 = the weakness-targeted session, labelled
               "what you'd do on a good day — parked, not cancelled"

# --- Normal day ---
else:
    Option 1 = weakness-targeted bike session   (Rule A + existing decide_type,
                                                 which already prefers a race
                                                 demand gap over the generic
                                                 curve comparison)
    Option 2 = contrast option:
        if week already has a hard session → endurance
        elif weekday == SUNDAY             → long ride w/ the profile's 90min
                                             ~45kph block
        else                               → second-choice type
                                             (lactate_threshold if primary was
                                             anaerobic/neuromuscular; endurance
                                             otherwise)
    Option 3 = strength focus (Rule C)
```

Why strength is always option 3 on normal days: it's a **different modality**,
so it doesn't compete for the same slot as options 1 and 2 — the athlete can
legitimately accept both a bike session and a strength session for the same day.
Options 1 and 2 are mutually exclusive; option 3 is additive. The UI must make
that distinction visible (see §4.2).

### 2.4 Rule C — weakest zone → strength focus

New function `suggest_strength_focus(weakest_zone_label, readiness, week_load)`
in `services/day_planner.py`. Returns `(focus_title, detail, reason)`.

| Weakest zone | Focus | Prescription | Why |
|---|---|---|---|
| **Neuromuscular** | Max-strength & explosive | Trap-bar deadlift or back squat **4x3-5 @ ≥85% 1RM**; box jumps / jump squats 3x5; single-leg step-ups. Full recovery, low reps, never to failure. | Sprint power is force-limited before it's aerobically limited. Same neuromuscular system as a 15s max effort. |
| **Anaerobic Capacity** | Heavy lower + trunk | Squat 4x5 @ 80%; Bulgarian split squat 3x8/leg; anti-rotation core (Pallof) 3x10. | Repeated 1min efforts draw on a force reserve; a bigger reserve means each surge costs a smaller fraction of max. |
| **VO2max** | Low-fatigue support only | RDL 3x10 moderate; single-leg glute bridge; plank / dead-bug. Controlled tempo, submaximal. | VO2max gains come from the bike. Gym work here must not steal recovery from the intervals that actually move this number. |
| **Functional Threshold** | Maintenance, <30min | Goblet squat 2x12-15 light; row; glute bridge. Well clear of the next threshold session. | Threshold is built by consistent time-on-bike. The gym's only job is to not get in the way. |
| **None (no signal)** | General full-body | Squat, hinge, row, overhead press — 2-3x8-10 moderate. | No weakness signal yet (needs weight + FTP logged). |

**Modifiers applied on top** (each is a further if/else):

```
if readiness verdict in (REST, EASY):
    → downgrade to mobility + core only, ≤20min, explicitly say why
if a hard bike session is planned today or tomorrow:
    → drop to maintenance volume; never prescribe ≥85% 1RM the day before
      or the day after a hard interval session
if weekday == FRIDAY and Saturday's team ride is planned:
    → maintenance only (don't arrive at the team ride pre-fatigued)
```

🚫 **Framing constraint, non-negotiable:** the athlete is 57kg, first-year
racing, and their stated strategy is to **gain** absolute power/mass, not cut to
a race weight. W/kg tracking in this app is already dynamic against today's
logged weight for exactly this reason. **No strength recommendation may be
framed as weight loss, leanness, or "getting lighter."** Frame as building
force, absolute power, and durability.

## 3. Backend work

### 3.1 `services/workout_types.py`

- Add `"neuromuscular"` to `WORKOUT_TYPES`, `_LABELS`, `_TARGETS`, `_GENERATORS`.
- Write `_neuromuscular(ftp_watts, intensity)` per §2.2.
- Everything downstream (AI type-parsing contract, the catalog endpoint, the
  builder UI) enumerates `WORKOUT_TYPES`, so this propagates for free —
  **that's the design intent of that list, don't bypass it.**

### 3.2 `services/day_planner.py`

- Extend `_COGGAN_ROW_TO_TYPE`: `"Neuromuscular" → "neuromuscular"`.
- Add `_HARD_WORKOUT_TYPES` membership for `neuromuscular` (it's a hard
  session — it must trigger the same spacing/stacking rules). Note the existing
  comment: this set is *deliberately* separate from `plan_reflow._HARD_TYPES`,
  which classifies stored `session_type` values (`intervals`/`long_ride`/
  `team_ride`) rather than catalog types. Conflating them was a real bug once.
- Add `suggest_strength_focus()` per §2.4.
- Add `compose_three_options()` per §2.3 — pure function, takes
  (weakest_zone, gap_report, planned_this_week, readiness_verdict, target_date),
  returns 3 option descriptors. No I/O, so it's directly unit-testable.

### 3.3 `api/main.py`

New: `GET /api/planned/{date}/suggestions`

Reuses the plumbing `coach_plan_day` already has: `_weakest_coggan_zone()`,
`_nearest_race_gap_report()`, `_resolved_ftp_watts()`,
`local_store.get_planned_workouts()` for the week, `compute_verdict` for
readiness, `day_planner.check_placement()` per option.

Response shape:

```jsonc
{
  "date": "2026-08-04",
  "weakest_zone": "Anaerobic Capacity (1min)",
  "weakest_zone_caveat": null,      // set when the row is a known-soft signal
  "readiness_verdict": "TRAIN",
  "ai_used": false,
  "ai_unavailable_message": "...",
  "options": [
    {
      "kind": "bike",               // bike | strength | rest | note
      "exclusive_with": ["bike"],   // which other kinds it competes with
      "workout_type": "anaerobic",
      "title": "Anaerobic capacity intervals",
      "detail": "8 x 30s @ 260-325W, 4min easy...",
      "reason": "Your weakest zone on the power profile is Anaerobic Capacity (1min).",
      "duration_min": 62,
      "placement_warning": null,
      "workout": { /* full PlannedWorkoutModel payload, ready to PUT */ }
    }
  ]
}
```

Each option's `workout` is a complete `PlannedWorkoutModel` payload, so "Add to
calendar" is a plain `PUT /api/planned/{date}` — **no new write endpoint.**

**AI boundary (requirement #2):** this endpoint is deterministic by default.
The AI layer (`ai_day_planner.enrich`) only runs when called with `?ai=true`,
and only ever rewrites `reason` prose / re-ranks within the existing catalog.
It can never invent a type, and any failure falls back silently to the
deterministic option. Same contract as today, just made explicit in the query
param.

### 3.4 Make plan generation opt-in (requirement #2)

`PlanView.jsx` currently auto-calls `api.weekPlan()` / `api.todayPlan()` on
mount. Change to: show the week's *stored* planned workouts (from
`/api/planned`), plus a "Generate a week" button that materialises the template.
The template algorithm itself (`services/training_plan.py`) doesn't change —
only *when* it runs. This makes Plan and Calendar agree.

⚠️ Verify before changing: several other panels (`AdaptiveRecommendation`,
`ReflowPanel`, `MorningBrief`'s `today_session`) read from `/api/plan/*`. Those
should keep working off the template as an *advisory* projection — the change is
that the template no longer implies anything is scheduled. Check each caller.

## 4. Frontend work

### 4.1 `AddCalendarEntryModal.jsx` (new)

Replaces the inline `.day-menu` block in `CalendarView.jsx`. Two-column
categorised grid, following the reference screenshot's layout, scoped to what's
meaningful in a cycling-only single-athlete app (i.e. **not** a 1:1 copy of
intervals.icu's list — no Run/Swim/Walk, no A/B/C race taxonomy until the race
model supports priorities, no Wellness Data since Garmin supplies it):

**Column 1 — Training**
- 🧠 **What should I do today?** → opens `TodaySuggestionPanel` (§4.2). Top slot.
- 🚴 **Structured workout** → blank workout + step editor (existing
  `addBlankWorkout` flow)
- 📚 **From my library** → existing saved-workout picker
- 🏋️ **Strength session** → quick-add with the focus dropdown
- ✨ **Generate this week** → existing `generateWeek`

**Column 2 — Context**
- 😴 **Rest day**
- 🤒 **Sick**
- ✈️ **Travel** → writes a 1-day window to the **existing constraints store**
- 📝 **Note**
- 🏁 **Race** → links to the existing Race tab rather than a parallel entry

Behaviour: Escape closes; backdrop click closes; each option either writes
immediately and closes, or swaps the modal body to a sub-panel. Reuse existing
`.modal-backdrop` / `.modal-panel` / `.followup-btn` classes — no new design
system.

### 4.2 `TodaySuggestionPanel.jsx` (new)

Renders the 3 options as cards. Per card:

- Title, duration, detail
- 💡 the `reason` string (always — the app's standing rule)
- ⚠️ `placement_warning` if present
- `WorkoutPreviewChart` for options with structured steps (reuse as-is)
- **[Add to calendar]** → `PUT /api/planned/{date}`, then close + reload
- **[Ask about this]** → inline follow-up, seeded with the option's context,
  posted to the existing `api.chat()` / `api.chatStream()`. **No new backend
  endpoint** — it's the same coach, given the suggestion as context.

Must make the exclusivity from §2.3 visible: options sharing a `kind` are
alternatives (adding one should offer to replace the other), while the strength
option is additive and can be added alongside. A quiet caption is enough —
don't build a selection state machine for it.

Degraded states to handle explicitly:
- No weight/FTP logged → no `weakest_zone`. Say *"log a weigh-in and an FTP
  test to get weakness-targeted suggestions"* and still return generic options.
  Never render an empty panel.
- Anthropic key invalid → `ai_unavailable_message` shown as a caption; the 3
  deterministic options still render. **The feature must work with the AI
  entirely offline.**

### 4.3 `CalendarView.jsx` (edit)

- Day click → `AddCalendarEntryModal` instead of the inline strip.
- `PLANNED_COLOR` gains the new session types.
- Fetch constraints; render ✈️ on travel-window days.
- Keep the existing empty-state copy — it already states the opt-in principle
  correctly.

### 4.4 `PlannedWorkoutModal.jsx` (edit)

- `SESSION_TYPES` gains `strength` / `note` / `sick`.
- For `strength`: swap the step editor for the focus dropdown + duration +
  notes (steps are meaningless), and add **[Mark as done]** → `POST /api/strength`
  per §1.2.

## 5. Build order

Bottom-up, each step independently verifiable:

1. `workout_types.py`: add `neuromuscular` + generator. **Test:** `build()`
   returns sane steps at several FTP values; unknown type still raises.
2. `day_planner.py`: `suggest_strength_focus()` + `compose_three_options()` +
   Neuromuscular mapping. **Test:** each weakness label → expected type and
   strength focus; Saturday/Monday/REST gates; no ≥85% 1RM adjacent to a hard day.
3. `GET /api/planned/{date}/suggestions`. **Test:** returns exactly 3; each
   `workout` payload round-trips through `PUT /api/planned/{date}` unchanged.
4. `TodaySuggestionPanel.jsx` — wired into the *existing* day menu first, so it's
   testable before the modal rewrite lands.
5. `AddCalendarEntryModal.jsx` + `CalendarView` rewrite.
6. New session types through `PlannedWorkoutModal` + colours + travel markers.
7. `PlanView` opt-in generation (§3.4), after auditing every `/api/plan/*` caller.
8. Full pass: `vite build`, backend smoke test on real cached data, browser
   screenshots light + dark.

## 6. Explicitly out of scope

- Multi-week / block-level AI plan generation. This feature is **per-day
  suggestions**. Adaptive periodization and plan reflow already own the week.
- Run/swim/multisport entries — the athlete is cycling-only.
- A/B/C race priorities — the race model has no priority field yet; adding one
  is its own change.
- Merging `strength_sessions` into `planned_workouts` (§1.2).
- Replacing `CoachPlanModal` — the 3-option panel supersedes it in the UI, but
  deleting it is a separate cleanup once the new flow is proven.

## 7. Open questions (assume the default, flag it, don't block)

1. **Sprint prescription unvalidated.** The 150-200% FTP / 10-15s / 4-5min-rest
   template is a literature-standard shape, not this athlete's tested numbers.
   Default: ship it, label it as a starting point.
2. **VO2max row may be a false weakness** — 5min is self-reported as non-maximal.
   Default: surface the caveat in the reason string rather than excluding the row.
3. **Strength 1RM is unknown.** Percentages are unusable without it. Default:
   express as RPE ("leave 2 reps in reserve") *and* %1RM, so it's actionable
   either way. A 1RM logger would be a follow-up feature.
4. **300km/week compliance** — is that still the team's requirement?
5. **Race calendar** still TBD — the race-demand-gap branch of `decide_type()`
   stays dormant until events with computed demand profiles exist.

---

# Session log

## Done

- [x] **Checkpoint commit** — batches 1–7's ~10.7k-line uncommitted diff
      committed as a baseline (`6c8c822`) before starting new work.
- [x] **Clutter audit.** Most of the remembered "11 tabs, overlapping features"
      problem was already fixed in an earlier pass (Overview → Power-only,
      weight trend → Readiness, phenotype → Athlete). Two real issues found
      and fixed:
  - [x] `MorningBrief` repeated the verdict headline `VerdictBanner` shows
        directly below it — removed the duplicate line + its dead CSS.
  - [x] `AdaptiveRecommendation` and `ReflowPanel` render back-to-back on Plan
        with identical styling and no labels — added a "Block phase" header to
        match "Week reflow".
  - Conclusion: no IA redesign needed.
- [x] **Feature spec above** (this document).

## In progress

- [ ] **Weekly 300km distance compliance tracker** — team requires 300km/week,
      never surfaced in the app. Partially built, *not yet verified*:
  - [x] `services/training_compliance.py` — Mon–Sun window, dedups by
        `activity_id` (the `data_query.py` pattern), returns distance/target/pace.
  - [x] `GET /api/plan/compliance`
  - [x] `api.js` → `planCompliance()`
  - [x] `WeeklyDistanceCompliance.jsx` (progress bar, on-pace/behind copy)
  - [ ] Wire into `PlanView.jsx`
  - [ ] `vite build` + browser verify (light + dark)
  - [ ] Smoke test against real cached activity data
  - [ ] Needs `.compliance-*` CSS — written against classes that don't exist yet

## Backlog (rough priority)

1. **Overreaching alert** — athlete-flagged signal (elevated resting HR +
   appetite change together). Needs a manual appetite/mood input that doesn't
   exist yet; bigger than it looks because of that missing input.
2. **CdA calculator** from the aero-profile fields already captured — currently
   capture-only, wired to nothing.
3. **Outdoor power ingestion** — the power meter was due ~early Aug 2026 (now).
   Check whether real outdoor power is already flowing through before assuming
   pipeline changes are needed.
4. **Race-date cross-reference** — `ConstraintsPanel`'s single race-date field
   and `RaceView`'s target-events list don't talk to each other. Smallest fix:
   default the former from the nearest upcoming event in the latter. Not a full
   merge — they do different jobs.
5. **Strength → Firestore schema** — logged today via `local_store`, flagged in
   memory as never scoped into Firestore. Check what actually persists first.
6. **Race peaking / taper** — the plan is still a flat 4-week cycle with no
   taper tied to a real race date.
