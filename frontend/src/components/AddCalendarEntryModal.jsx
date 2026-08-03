import { useEffect, useState } from "react";
import { api } from "../api";
import TodaySuggestionPanel from "./TodaySuggestionPanel";

// The intervals.icu-style "Add Calendar Entry" picker, scoped to this app.
//
// Deliberately NOT a 1:1 copy of intervals.icu's list. Run / Swim / Walk /
// Other are omitted because this is a cycling-only single-athlete app; the
// A/B/C race taxonomy is omitted because the race model has no priority field
// yet, and inventing one here would put a second, conflicting race concept
// next to the Race tab's; Wellness Data is omitted because Garmin supplies it
// automatically and a manual entry point would just create a second source of
// truth for the same numbers.
//
// Travel writes to the EXISTING constraints store that the planner already
// reads, rather than a parallel travel concept that only the calendar knows
// about.

const STRENGTH_FOCUSES = [
  ["full_body", "Full body"],
  ["lower_body", "Lower body"],
  ["upper_body", "Upper body"],
  ["core", "Core"],
  ["general", "General"],
];

function Option({ icon, label, hint, onClick, disabled, title }) {
  return (
    <button className="entry-option" onClick={onClick} disabled={disabled} title={title}>
      <span className="entry-option-icon">{icon}</span>
      <span className="entry-option-body">
        <span className="entry-option-label">{label}</span>
        {hint && <span className="entry-option-hint">{hint}</span>}
      </span>
    </button>
  );
}

export default function AddCalendarEntryModal({
  date,
  ftpWatts,
  library = [],
  onClose,
  onSavePlanned,
  onGenerateWeek,
  onChanged,
}) {
  const [panel, setPanel] = useState(null); // null | suggestions | library | strength | note
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [strength, setStrength] = useState({ focus: "full_body", duration_min: 45, notes: "" });
  const [note, setNote] = useState("");

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const savePlanned = (workout) => run(async () => {
    await onSavePlanned(date, workout);
    onClose();
  });

  const addStrength = () =>
    savePlanned({
      session_type: "strength",
      title: `Strength — ${STRENGTH_FOCUSES.find(([v]) => v === strength.focus)?.[1] ?? "session"}`,
      detail: strength.notes,
      duration_min: strength.duration_min,
      steps: [],
      source: "custom",
    });

  const addNote = () =>
    savePlanned({
      session_type: "note", title: note.slice(0, 60) || "Note",
      detail: note, steps: [], source: "custom",
    });

  const addSimple = (session_type, title, detail) =>
    savePlanned({ session_type, title, detail, steps: [], source: "custom" });

  // Travel is a constraint, not a session: it goes to the store the planner
  // already consults so the plan actually reflects it, instead of only
  // showing a chip on the calendar.
  const addTravel = () =>
    run(async () => {
      const current = await api.getConstraints();
      await api.saveConstraints({
        race_date: current.race_date || null,
        travel_windows: [...(current.travel_windows || []), { start: date, end: date, note: "" }],
      });
      onChanged?.();
      onClose();
    });

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel modal-panel-wide" onClick={(e) => e.stopPropagation()}>
        <div className="calendar-nav">
          <h3 style={{ margin: 0 }}>Add calendar entry — {date}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close" title="Close">
            ✕
          </button>
        </div>

        {error && <div className="error-box">{error}</div>}

        {panel === null && (
          <div className="entry-grid">
            <div className="entry-column">
              <div className="caption">Training</div>
              <Option
                icon="🧠" label="What should I do?"
                hint="Three options built from your power-curve weakness"
                onClick={() => setPanel("suggestions")} disabled={busy}
              />
              <Option
                icon="🚴" label="Structured workout"
                hint="Build intervals step by step"
                onClick={() => savePlanned({
                  session_type: "custom", title: "New workout", detail: "", source: "custom",
                  steps: [{ duration_sec: 300, target_type: "steady", target_low_pct_ftp: 0.75 }],
                })}
                disabled={busy}
              />
              <Option
                icon="📚" label="From my library"
                hint={library.length ? `${library.length} saved` : "No saved workouts yet"}
                onClick={() => setPanel("library")}
                disabled={busy || library.length === 0}
                title={library.length === 0 ? "Build one in the Builder tab first" : undefined}
              />
              <Option
                icon="🏋️" label="Strength session"
                onClick={() => setPanel("strength")} disabled={busy}
              />
              <Option
                icon="✨" label="Generate this week"
                hint="Fill the whole week from your plan"
                onClick={() => run(async () => { await onGenerateWeek(date); onClose(); })}
                disabled={busy}
              />
            </div>

            <div className="entry-column">
              <div className="caption">Context</div>
              <Option
                icon="😴" label="Rest day"
                onClick={() => addSimple("rest", "Rest day", "No structured session.")}
                disabled={busy}
              />
              <Option
                icon="🤒" label="Sick"
                hint="Logged, not judged"
                onClick={() => addSimple("sick", "Sick", "Not training — unwell.")}
                disabled={busy}
              />
              <Option
                icon="✈️" label="Travel"
                hint="Adds a travel window the planner respects"
                onClick={addTravel} disabled={busy}
              />
              <Option icon="📝" label="Note" onClick={() => setPanel("note")} disabled={busy} />
              <Option
                icon="🏁" label="Race"
                hint="Target events live on the Race tab, with course demand"
                onClick={() => setPanel("race")} disabled={busy}
              />
            </div>
          </div>
        )}

        {panel !== null && (
          <button className="followup-btn" onClick={() => setPanel(null)} style={{ alignSelf: "flex-start" }}>
            ← Back
          </button>
        )}

        {panel === "suggestions" && (
          <TodaySuggestionPanel
            date={date}
            ftpWatts={ftpWatts}
            onAdded={() => { onChanged?.(); onClose(); }}
          />
        )}

        {panel === "library" && (
          <div className="day-menu-library">
            {library.map((w) => (
              <button
                key={w.id} className="followup-btn" disabled={busy}
                onClick={() => savePlanned({
                  session_type: "custom", title: w.name, detail: w.description || "",
                  source: "custom", steps: w.steps,
                })}
              >
                {w.name} ({w.steps.length} steps)
              </button>
            ))}
          </div>
        )}

        {panel === "strength" && (
          <>
            <div className="builder-step">
              <select
                value={strength.focus}
                onChange={(e) => setStrength({ ...strength, focus: e.target.value })}
              >
                {STRENGTH_FOCUSES.map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
              <input
                type="number" min="5"
                value={strength.duration_min}
                onChange={(e) => setStrength({ ...strength, duration_min: Number(e.target.value) })}
              />
              <span className="step-unit">min</span>
              <input
                className="goal-input-wide" placeholder="notes (optional)"
                value={strength.notes}
                onChange={(e) => setStrength({ ...strength, notes: e.target.value })}
              />
            </div>
            <div className="modal-actions">
              <button className="primary-btn" onClick={addStrength} disabled={busy}>
                {busy ? "Adding…" : "Add to calendar"}
              </button>
            </div>
          </>
        )}

        {panel === "note" && (
          <>
            <label className="modal-field">
              Note
              <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
            <div className="modal-actions">
              <button className="primary-btn" onClick={addNote} disabled={busy || !note.trim()}>
                {busy ? "Adding…" : "Add to calendar"}
              </button>
            </div>
          </>
        )}

        {panel === "race" && (
          <div className="empty-note">
            Races are managed on the <strong>Race</strong> tab, where a GPX gets turned into a course
            demand profile and compared against your power curve. Adding one here would create a second
            race list that the demand modelling couldn't see.
          </div>
        )}
      </div>
    </div>
  );
}
