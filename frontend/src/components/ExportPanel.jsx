import { useState } from "react";
import { api } from "../api";
import { toIsoDateLocal } from "../dateUtils";
import TimeRangePicker from "./TimeRangePicker";

const CATEGORY_LABELS = {
  wellness: "Wellness (HRV, readiness, sleep, etc.)",
  activities: "Activities",
  weight: "Weight",
  ftp_history: "FTP history",
  strength_sessions: "Strength sessions",
  workouts: "Saved workouts",
  goals: "Goals",
};

// TimeRangePicker only fires onChange on a click, not on mount — so the
// default range shown ("3M", active-looking) needs its own matching initial
// state here, or the Download button stays silently disabled until the user
// clicks a preset that's already visually selected.
function defaultRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 90);
  return { start: toIsoDateLocal(start), end: toIsoDateLocal(end) };
}

export default function ExportPanel() {
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState(defaultRange);
  const [categories, setCategories] = useState(Object.keys(CATEGORY_LABELS));
  const [format, setFormat] = useState("json");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const toggleCategory = (cat) => {
    setCategories((cs) => (cs.includes(cat) ? cs.filter((c) => c !== cat) : [...cs, cat]));
  };

  const doExport = async () => {
    if (!range || categories.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await api.exportData({ start: range.start, end: range.end, categories, format });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="export-panel">
      <button className="followup-btn" onClick={() => setOpen((o) => !o)}>
        {open ? "Hide export" : "📤 Export data"}
      </button>
      {open && (
        <div className="export-panel-body">
          <TimeRangePicker onChange={setRange} defaultPreset="3M" />
          <div className="export-category-grid">
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
              <label key={key} className="export-category-item">
                <input type="checkbox" checked={categories.includes(key)} onChange={() => toggleCategory(key)} />
                {label}
              </label>
            ))}
          </div>
          <div className="export-format-row">
            <span className="caption">Format:</span>
            <button className={format === "json" ? "range-btn active" : "range-btn"} onClick={() => setFormat("json")}>
              JSON
            </button>
            <button className={format === "csv" ? "range-btn active" : "range-btn"} onClick={() => setFormat("csv")}>
              CSV (.zip)
            </button>
          </div>
          {error && <div className="error-box">{error}</div>}
          <button className="primary-btn" onClick={doExport} disabled={busy || !range || categories.length === 0}>
            {busy ? "Preparing..." : "Download"}
          </button>
        </div>
      )}
    </div>
  );
}
