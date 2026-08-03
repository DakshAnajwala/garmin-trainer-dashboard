import { useEffect, useState } from "react";
import { api } from "../api";

// "You give it life; it solves the block around reality" — a race date and
// travel windows the athlete declares, which the plan and coach both take
// into account instead of prescribing sessions in a vacuum.
export default function ConstraintsPanel({ onChanged }) {
  const [open, setOpen] = useState(false);
  const [raceDate, setRaceDate] = useState("");
  const [windows, setWindows] = useState([]);
  const [form, setForm] = useState({ start: "", end: "", note: "" });
  const [saving, setSaving] = useState(false);

  const load = () =>
    api.getConstraints().then((c) => {
      setRaceDate(c.race_date || "");
      setWindows(c.travel_windows || []);
    });

  useEffect(() => {
    load();
  }, []);

  const persist = async (next) => {
    setSaving(true);
    try {
      await api.saveConstraints(next);
      onChanged?.();
    } finally {
      setSaving(false);
    }
  };

  const saveRaceDate = () => persist({ race_date: raceDate || null, travel_windows: windows });

  const addWindow = () => {
    if (!form.start || !form.end) return;
    const next = [...windows, form];
    setWindows(next);
    setForm({ start: "", end: "", note: "" });
    persist({ race_date: raceDate || null, travel_windows: next });
  };

  const removeWindow = (i) => {
    const next = windows.filter((_, idx) => idx !== i);
    setWindows(next);
    persist({ race_date: raceDate || null, travel_windows: next });
  };

  return (
    <div className="constraints-panel">
      <button className="followup-btn" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide constraints" : "🏁 Race date & travel"}
      </button>
      {open && (
        <div className="constraints-body">
          <label className="constraints-race">
            Race date:
            <input type="date" value={raceDate} onChange={(e) => setRaceDate(e.target.value)} onBlur={saveRaceDate} />
          </label>

          <div className="caption">
            Travel windows override the plan for those days regardless of what the weekly template says — including
            the Saturday slot, since this is you telling the app you're unavailable, not the coach suggesting a skip.
          </div>

          {windows.map((w, i) => (
            <div className="constraints-window" key={i}>
              <span>
                {w.start} → {w.end}
                {w.note ? ` — ${w.note}` : ""}
              </span>
              <button className="step-remove" onClick={() => removeWindow(i)}>
                ✕
              </button>
            </div>
          ))}

          <div className="builder-step">
            <input type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
            <input type="date" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
            <input
              className="goal-input-wide"
              placeholder="note (e.g. conference trip)"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
            />
            <button className="primary-btn" onClick={addWindow} disabled={!form.start || !form.end}>
              Add
            </button>
          </div>
          {saving && <div className="caption">Saving...</div>}
        </div>
      )}
    </div>
  );
}
