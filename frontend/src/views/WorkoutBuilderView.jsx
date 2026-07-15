import { useEffect, useState } from "react";
import { api } from "../api";
import WorkoutPreviewChart from "../components/WorkoutPreviewChart";

const BLANK_STEP = { duration_sec: 300, target_type: "steady", target_low_pct_ftp: 0.75, target_high_pct_ftp: null };

function emptyWorkout() {
  return { id: null, name: "New workout", description: "", steps: [{ ...BLANK_STEP }] };
}

export default function WorkoutBuilderView({ ftpWatts }) {
  const [workout, setWorkout] = useState(emptyWorkout);
  const [saved, setSaved] = useState([]);
  const [status, setStatus] = useState(null);

  const refreshSaved = () => api.listWorkouts().then(setSaved).catch(() => {});
  useEffect(() => {
    refreshSaved();
  }, []);

  const updateStep = (i, patch) => {
    setWorkout((w) => ({ ...w, steps: w.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) }));
  };

  const addStep = () => setWorkout((w) => ({ ...w, steps: [...w.steps, { ...BLANK_STEP }] }));
  const removeStep = (i) => setWorkout((w) => ({ ...w, steps: w.steps.filter((_, idx) => idx !== i) }));

  const loadWednesday = async () => {
    const tpl = await api.wednesdayTemplate();
    setWorkout({ id: null, ...tpl });
    setStatus("Loaded this week's Wednesday session — edit freely.");
  };

  const save = async () => {
    const result = await api.saveWorkout(workout);
    setWorkout(result);
    setStatus("Saved.");
    refreshSaved();
  };

  const exportZwo = async () => {
    const res = await fetch(api.exportZwoUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(workout),
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${workout.name.replace(/\W+/g, "_")}.zwo`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const loadSaved = (w) => {
    setWorkout(JSON.parse(JSON.stringify(w)));
    setStatus(`Loaded "${w.name}".`);
  };

  const del = async (id) => {
    await api.deleteWorkout(id);
    refreshSaved();
  };

  return (
    <div className="view-grid">
      <div className="builder-toolbar">
        <button className="followup-btn" onClick={() => setWorkout(emptyWorkout())}>
          + New
        </button>
        <button className="followup-btn" onClick={loadWednesday}>
          Load this week's Wednesday session
        </button>
      </div>

      <input
        className="builder-name"
        value={workout.name}
        onChange={(e) => setWorkout({ ...workout, name: e.target.value })}
      />

      <WorkoutPreviewChart steps={workout.steps} ftpWatts={ftpWatts} />

      <div className="builder-steps">
        {workout.steps.map((s, i) => (
          <div className="builder-step" key={i}>
            <input
              type="number"
              min="10"
              step="10"
              value={Math.round(s.duration_sec / 60)}
              onChange={(e) => updateStep(i, { duration_sec: Math.max(10, Number(e.target.value) * 60) })}
              title="minutes"
            />
            <span className="step-unit">min</span>
            <select value={s.target_type} onChange={(e) => updateStep(i, { target_type: e.target.value })}>
              <option value="steady">steady</option>
              <option value="range">range</option>
              <option value="ramp">ramp</option>
            </select>
            <input
              type="number"
              min="30"
              max="200"
              value={Math.round(s.target_low_pct_ftp * 100)}
              onChange={(e) => updateStep(i, { target_low_pct_ftp: Number(e.target.value) / 100 })}
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
                  onChange={(e) => updateStep(i, { target_high_pct_ftp: Number(e.target.value) / 100 })}
                  title="% FTP high"
                />
              </>
            )}
            <span className="step-unit">% FTP</span>
            {ftpWatts && (
              <span className="step-watts">
                {Math.round(s.target_low_pct_ftp * ftpWatts)}
                {s.target_type !== "steady" ? `–${Math.round((s.target_high_pct_ftp ?? s.target_low_pct_ftp) * ftpWatts)}` : ""}W
              </span>
            )}
            <button className="step-remove" onClick={() => removeStep(i)}>
              ✕
            </button>
          </div>
        ))}
        <button className="followup-btn" onClick={addStep}>
          + Add step
        </button>
      </div>

      <div className="builder-actions">
        <button className="primary-btn" onClick={save}>
          Save
        </button>
        <button className="followup-btn" onClick={exportZwo}>
          Export .ZWO (Zwift/KICKR)
        </button>
        {status && <span className="caption">{status}</span>}
      </div>

      {saved.length > 0 && (
        <>
          <h3>Saved workouts</h3>
          <div className="saved-workouts">
            {saved.map((w) => (
              <div className="saved-workout" key={w.id}>
                <button className="followup-btn" onClick={() => loadSaved(w)}>
                  {w.name} ({w.steps.length} steps)
                </button>
                <button className="step-remove" onClick={() => del(w.id)}>
                  ✕
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
