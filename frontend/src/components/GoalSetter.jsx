import { useEffect, useState } from "react";
import { api } from "../api";
import { colors } from "../theme";

const DURATION_LABELS = ["Neuromuscular (~15s)", "Anaerobic Capacity (1min)", "VO2max (5min)", "Functional Threshold (FTP)"];
const CATEGORIES = ["Cat 5", "Cat 4", "Cat 3", "Cat 2", "Cat 1", "Pro/UCI"];

function matchRow(cogganProfile, durationLabel) {
  if (!cogganProfile?.available) return null;
  return cogganProfile.rows.find((r) => r.label.startsWith(durationLabel.split(" (")[0])) ?? null;
}

// Falls back to a category-band-derived target (bodyweight × the band's w/kg
// threshold) when the goal has no explicit target_watts, mirroring how
// prefillFromBand computes it.
function computeProgress(goal, cogganProfile) {
  const row = matchRow(cogganProfile, goal.duration_label);
  if (!row) return null;
  const weightKg = row.wkg ? row.watts / row.wkg : null;
  let targetWatts = goal.target_watts;
  if (!targetWatts && weightKg && row.bands[goal.category] != null) {
    targetWatts = row.bands[goal.category] * weightKg;
  }
  if (!targetWatts) return null;
  const pct = Math.max(0, Math.min(100, Math.round((row.watts / targetWatts) * 100)));
  return {
    currentWatts: row.watts,
    currentWkg: row.wkg,
    targetWatts: Math.round(targetWatts),
    pct,
    remaining: Math.max(0, Math.round(targetWatts - row.watts)),
    met: row.watts >= targetWatts,
  };
}

function progressColor(pct) {
  if (pct >= 100) return colors.good;
  if (pct >= 75) return colors.blue;
  if (pct >= 40) return colors.warning;
  return colors.critical;
}

export default function GoalSetter({ cogganProfile }) {
  const [goals, setGoals] = useState([]);
  const [form, setForm] = useState({ title: "", category: "Cat 2", duration_label: DURATION_LABELS[3], target_watts: "" });

  const refresh = () => api.listGoals().then(setGoals).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const prefillFromBand = () => {
    if (!cogganProfile?.available) return;
    const row = cogganProfile.rows.find((r) => r.label.startsWith(form.duration_label.split(" (")[0]));
    if (row) {
      const targetWkg = row.bands[form.category];
      const weightKg = row.wkg ? row.watts / row.wkg : null;
      setForm((f) => ({ ...f, target_watts: weightKg ? Math.round(targetWkg * weightKg) : "" }));
    }
  };

  const save = async () => {
    await api.saveGoal({ ...form, target_watts: form.target_watts ? Number(form.target_watts) : null });
    setForm({ title: "", category: "Cat 2", duration_label: DURATION_LABELS[3], target_watts: "" });
    refresh();
  };

  const del = async (id) => {
    await api.deleteGoal(id);
    refresh();
  };

  return (
    <div className="goal-setter">
      <div className="builder-step">
        <input
          className="goal-input-wide"
          placeholder="Goal title"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <select value={form.duration_label} onChange={(e) => setForm({ ...form, duration_label: e.target.value })}>
          {DURATION_LABELS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <button className="followup-btn" onClick={prefillFromBand}>
          Prefill target from Coggan band
        </button>
        <input
          type="number"
          className="goal-input-wide"
          placeholder="target watts"
          value={form.target_watts}
          onChange={(e) => setForm({ ...form, target_watts: e.target.value })}
        />
        <button className="primary-btn" onClick={save} disabled={!form.title}>
          Add goal
        </button>
      </div>

      <div className="plan-week">
        {goals.map((g) => {
          const progress = computeProgress(g, cogganProfile);
          return (
            <div className="plan-card" key={g.id}>
              <div className="plan-card-top">
                <span className="plan-card-day">{g.category}</span>
                <button className="step-remove" onClick={() => del(g.id)}>
                  ✕
                </button>
              </div>
              <div className="plan-card-title">{g.title}</div>
              <div className="plan-card-detail">
                {g.duration_label} {g.target_watts ? `— target ${g.target_watts}W` : ""}
              </div>
              {progress && (
                <>
                  <div className="goal-progress-track">
                    <div
                      className="goal-progress-fill"
                      style={{ width: `${progress.pct}%`, background: progressColor(progress.pct) }}
                    />
                  </div>
                  <div className="goal-progress-label">
                    <span>
                      {progress.currentWatts}W ({progress.currentWkg} W/kg) of {progress.targetWatts}W
                    </span>
                    <span style={{ color: progressColor(progress.pct) }}>
                      {progress.met ? "Target met" : `${progress.remaining}W to go`}
                    </span>
                  </div>
                </>
              )}
            </div>
          );
        })}
        {goals.length === 0 && <div className="empty-note">No goals set yet.</div>}
      </div>
    </div>
  );
}
