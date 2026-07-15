import { useEffect, useState } from "react";
import { api } from "../api";

export default function StrengthLog() {
  const [sessions, setSessions] = useState([]);
  const [form, setForm] = useState({ session_type: "general", duration_min: 45, notes: "" });

  const refresh = () => api.strengthSessions(90).then(setSessions).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const log = async () => {
    await api.logStrength(form);
    setForm({ session_type: "general", duration_min: 45, notes: "" });
    refresh();
  };

  const del = async (id) => {
    await api.deleteStrength(id);
    refresh();
  };

  return (
    <div className="strength-log">
      <div className="builder-step">
        <select value={form.session_type} onChange={(e) => setForm({ ...form, session_type: e.target.value })}>
          <option value="general">General</option>
          <option value="lower_body">Lower body</option>
          <option value="upper_body">Upper body</option>
          <option value="core">Core</option>
          <option value="full_body">Full body</option>
        </select>
        <input
          type="number"
          value={form.duration_min}
          onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
        />
        <span className="step-unit">min</span>
        <input
          placeholder="notes (optional)"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
        <button className="primary-btn" onClick={log}>
          Log session
        </button>
      </div>

      <div className="activity-list">
        {sessions
          .slice()
          .reverse()
          .map((s) => (
            <div className="activity-row" key={s.id} style={{ cursor: "default" }}>
              <span className="activity-icon">🏋️</span>
              <span className="activity-main">
                <span className="activity-name">{s.session_type.replace("_", " ")}</span>
                <span className="activity-sub">
                  {s.date} {s.notes ? `— ${s.notes}` : ""}
                </span>
              </span>
              <span className="activity-stats">
                <span>{s.duration_min}min</span>
              </span>
              <button className="step-remove" onClick={() => del(s.id)}>
                ✕
              </button>
            </div>
          ))}
        {sessions.length === 0 && <div className="empty-note">No strength sessions logged yet.</div>}
      </div>
    </div>
  );
}
