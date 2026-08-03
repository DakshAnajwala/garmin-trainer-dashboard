import { useEffect, useState } from "react";
import WorkoutPreviewChart from "./WorkoutPreviewChart";

// Click a planned day → this. intervals.icu-style: see the workout, its step
// profile, and edit or delete it in place. Structured sessions (the generated
// intervals day) get the full step editor reused from the Workout Builder;
// simple endurance/rest days just edit their title, type and duration, because
// inventing fake interval steps for "ride easy for 75min" would be noise.

const BLANK_STEP = { duration_sec: 300, target_type: "steady", target_low_pct_ftp: 0.75, target_high_pct_ftp: null };

const SESSION_TYPES = [
  ["endurance", "Endurance"],
  ["intervals", "Intervals"],
  ["long_ride", "Long ride"],
  ["team_ride", "Team ride"],
  ["rest", "Rest"],
  ["custom", "Custom"],
];

function fmtStep(s) {
  const min = Math.round(s.duration_sec / 60);
  const low = Math.round(s.target_low_pct_ftp * 100);
  const cadence =
    s.cadence_low_rpm != null || s.cadence_high_rpm != null
      ? ` @ ${s.cadence_low_rpm ?? s.cadence_high_rpm}-${s.cadence_high_rpm ?? s.cadence_low_rpm}rpm`
      : "";
  if (s.target_type === "steady") return `${min}min @ ${low}% FTP${cadence}`;
  const high = Math.round((s.target_high_pct_ftp ?? s.target_low_pct_ftp) * 100);
  return `${min}min ${s.target_type} ${low}→${high}% FTP${cadence}`;
}

export default function PlannedWorkoutModal({ date, planned, ftpWatts, onSave, onDelete, onClose }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(planned);
  const [busy, setBusy] = useState(false);

  // A fresh planned prop (different day clicked) resets the modal's state.
  useEffect(() => {
    setDraft(planned);
    setEditing(false);
  }, [planned, date]);

  // Close on Escape — modals that only close by mouse are a papercut.
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const steps = draft.steps || [];
  const patchStep = (i, patch) =>
    setDraft((d) => ({ ...d, steps: d.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) }));
  const addStep = () => setDraft((d) => ({ ...d, steps: [...(d.steps || []), { ...BLANK_STEP }] }));
  const removeStep = (i) => setDraft((d) => ({ ...d, steps: d.steps.filter((_, idx) => idx !== i) }));

  const totalMin = steps.reduce((sum, s) => sum + Math.round(s.duration_sec / 60), 0);

  const save = async () => {
    setBusy(true);
    try {
      // Editing makes it yours — retag so the calendar shows "your session"
      // and a future regenerate leaves it alone.
      await onSave(date, { ...draft, source: "custom" });
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="calendar-nav">
          <h3 style={{ margin: 0 }}>{date}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close" title="Close">
            ✕
          </button>
        </div>

        {editing ? (
          <>
            <label className="modal-field">
              Title
              <input value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
            </label>
            <div className="modal-row">
              <label className="modal-field">
                Type
                <select value={draft.session_type} onChange={(e) => setDraft((d) => ({ ...d, session_type: e.target.value }))}>
                  {SESSION_TYPES.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className="modal-field">
                Duration (min)
                <input
                  type="number"
                  min="0"
                  value={draft.duration_min ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, duration_min: e.target.value ? Number(e.target.value) : null }))}
                />
              </label>
            </div>
            <label className="modal-field">
              Notes
              <textarea rows={2} value={draft.detail || ""} onChange={(e) => setDraft((d) => ({ ...d, detail: e.target.value }))} />
            </label>

            {steps.length > 0 && <WorkoutPreviewChart steps={steps} ftpWatts={ftpWatts} />}

            <div className="builder-steps">
              {steps.map((s, i) => (
                <div className="builder-step" key={i}>
                  <input
                    type="number"
                    min="1"
                    value={Math.round(s.duration_sec / 60)}
                    onChange={(e) => patchStep(i, { duration_sec: Math.max(10, Number(e.target.value) * 60) })}
                    title="minutes"
                  />
                  <span className="step-unit">min</span>
                  <select value={s.target_type} onChange={(e) => patchStep(i, { target_type: e.target.value })}>
                    <option value="steady">steady</option>
                    <option value="range">range</option>
                    <option value="ramp">ramp</option>
                  </select>
                  <input
                    type="number"
                    min="30"
                    max="200"
                    value={Math.round(s.target_low_pct_ftp * 100)}
                    onChange={(e) => patchStep(i, { target_low_pct_ftp: Number(e.target.value) / 100 })}
                    title="% FTP low"
                  />
                  {s.target_type !== "steady" && (
                    <>
                      <span className="step-unit">→</span>
                      <input
                        type="number"
                        min="30"
                        max="200"
                        value={Math.round((s.target_high_pct_ftp ?? s.target_low_pct_ftp) * 100)}
                        onChange={(e) => patchStep(i, { target_high_pct_ftp: Number(e.target.value) / 100 })}
                        title="% FTP high"
                      />
                    </>
                  )}
                  <span className="step-unit">% FTP</span>
                  {ftpWatts != null && (
                    <span className="step-watts">
                      {Math.round(s.target_low_pct_ftp * ftpWatts)}
                      {s.target_type !== "steady" ? `–${Math.round((s.target_high_pct_ftp ?? s.target_low_pct_ftp) * ftpWatts)}` : ""}W
                    </span>
                  )}
                  {s.cadence_low_rpm != null || s.cadence_high_rpm != null ? (
                    <>
                      <input
                        type="number"
                        min="30"
                        max="120"
                        value={s.cadence_low_rpm ?? ""}
                        onChange={(e) => patchStep(i, { cadence_low_rpm: e.target.value ? Number(e.target.value) : null })}
                        title="cadence low rpm"
                        style={{ width: 48 }}
                      />
                      <span className="step-unit">–</span>
                      <input
                        type="number"
                        min="30"
                        max="120"
                        value={s.cadence_high_rpm ?? ""}
                        onChange={(e) => patchStep(i, { cadence_high_rpm: e.target.value ? Number(e.target.value) : null })}
                        title="cadence high rpm"
                        style={{ width: 48 }}
                      />
                      <span className="step-unit">rpm</span>
                      <button className="followup-btn" onClick={() => patchStep(i, { cadence_low_rpm: null, cadence_high_rpm: null })} title="Remove cadence target">
                        no cadence
                      </button>
                    </>
                  ) : (
                    <button className="followup-btn" onClick={() => patchStep(i, { cadence_low_rpm: 50, cadence_high_rpm: 60 })} title="Add a cadence target (e.g. overgearing work)">
                      + cadence
                    </button>
                  )}
                  <button className="followup-btn" onClick={() => removeStep(i)} title="Remove step">
                    ✕
                  </button>
                </div>
              ))}
              <button className="followup-btn" onClick={addStep}>
                + Add step
              </button>
            </div>

            <div className="modal-actions">
              <button className="primary-btn" onClick={save} disabled={busy || !draft.title?.trim()}>
                {busy ? "Saving…" : "Save"}
              </button>
              <button className="followup-btn" onClick={() => { setDraft(planned); setEditing(false); }}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="plan-card-top">
              <span className="plan-card-title">{planned.title}</span>
              <span className={`plan-badge ${planned.source === "custom" ? "badge-blue" : "badge-muted"}`}>
                {planned.source === "custom" ? "your session" : "suggested"}
              </span>
            </div>
            {planned.detail && <div className="plan-card-detail">{planned.detail}</div>}
            {planned.duration_min && <div className="plan-card-meta">{planned.duration_min} min planned</div>}

            {steps.length > 0 ? (
              <>
                <WorkoutPreviewChart steps={steps} ftpWatts={ftpWatts} />
                <div className="caption">{steps.length} steps · {totalMin} min total</div>
                <ol className="planned-step-list">
                  {steps.map((s, i) => (
                    <li key={i} className="data-field">
                      {fmtStep(s)}
                      {ftpWatts != null && s.target_type === "steady" && (
                        <span className="step-watts"> {Math.round(s.target_low_pct_ftp * ftpWatts)}W</span>
                      )}
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <div className="caption">No structured steps — this is a target range, not an interval set.</div>
            )}

            <div className="modal-actions">
              <button className="primary-btn" onClick={() => setEditing(true)}>
                Edit
              </button>
              <button
                className="followup-btn danger-btn"
                onClick={() => {
                  if (window.confirm(`Delete the planned "${planned.title}" on ${date}?`)) onDelete(date);
                }}
              >
                Delete
              </button>
              <button className="followup-btn" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
