import { useEffect, useState } from "react";
import { api } from "../api";
import WorkoutPreviewChart from "./WorkoutPreviewChart";

// "Let my coach plan for me" — the day-planner's AI-facing surface.
//
// This is a PREVIEW-then-confirm flow, same rule as every other visible
// recommendation in this app (the readiness advisory, adaptive periodization,
// plan reflow): the athlete sees the reasoning and approves it, nothing lands
// on the calendar silently. The "reason" and "placement_warning" strings come
// straight from services/day_planner.py, which is deterministic — this works
// today even with the Anthropic key invalid. If an AI layer is added later to
// enrich the type choice, this same preview/confirm shape is what it plugs into.
export default function CoachPlanModal({ date, ftpWatts, onClose, onConfirm }) {
  const [types, setTypes] = useState([]);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.workoutTypeCatalog().then((d) => setTypes(d.types)).catch(() => {});
  }, []);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const plan = async (workoutType) => {
    setLoading(true);
    setError(null);
    try {
      setPreview(await api.coachPlanDay(date, workoutType));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm(date, { ...preview.workout, source: "coach" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="calendar-nav">
          <h3 style={{ margin: 0 }}>Let my coach plan — {date}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close" title="Close">
            ✕
          </button>
        </div>

        {!preview && (
          <>
            <div className="caption">
              Pick a workout type, or let the plan decide based on your weakest zone and this week's load.
            </div>
            <div className="followup-row">
              <button className="primary-btn" onClick={() => plan(null)} disabled={loading}>
                {loading ? "Thinking…" : "🧠 Decide for me"}
              </button>
              {types.map((t) => (
                <button key={t.key} className="followup-btn" onClick={() => plan(t.key)} disabled={loading}>
                  {t.label}
                </button>
              ))}
            </div>
            {error && <div className="error-box">{error}</div>}
          </>
        )}

        {preview && (
          <>
            {preview.reason && (
              <div className="junk-notice">
                <span>💡 {preview.reason}</span>
              </div>
            )}
            {preview.placement_warning && (
              <div className="junk-notice">
                <span>⚠️ {preview.placement_warning}</span>
              </div>
            )}
            {/* The AI layer only enriches the type choice + rationale — this
                deterministic preview always works even when it can't run, so
                the message is informational, not a blocker. */}
            {preview.ai_unavailable_message && (
              <div className="caption">🤖 {preview.ai_unavailable_message}</div>
            )}

            <div className="plan-card-top">
              <span className="plan-card-title">{preview.workout.title}</span>
              <span className="plan-badge badge-blue">coach-planned</span>
            </div>
            <div className="plan-card-detail">{preview.workout.detail}</div>
            <div className="plan-card-meta">{preview.workout.duration_min} min</div>

            {preview.workout.steps?.length > 0 && (
              <WorkoutPreviewChart steps={preview.workout.steps} ftpWatts={ftpWatts} />
            )}

            <div className="modal-actions">
              <button className="primary-btn" onClick={confirm} disabled={busy}>
                {busy ? "Adding…" : "Add to calendar"}
              </button>
              <button className="followup-btn" onClick={() => setPreview(null)} disabled={busy}>
                Try a different type
              </button>
              <button className="followup-btn" onClick={onClose} disabled={busy}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
