import { useEffect, useRef, useState } from "react";
import { api } from "../api";

// F1: course-specific demand modeling. Upload the race route, get "what this
// event asks of you" vs what your model says you currently have.

const GAP_BADGE = { ok: "badge-good", stretch: "badge-warning", gap: "badge-critical" };

function DemandProfile({ profile }) {
  if (!profile) return null;
  const { course, derates, conditions, demands, gap_report, diff_vs_previous } = profile;
  return (
    <div className="view-grid">
      {diff_vs_previous && diff_vs_previous.length > 0 && (
        <div className="junk-notice">
          <span>
            <strong>Since last computation:</strong> {diff_vs_previous.join(" · ")}
          </span>
        </div>
      )}

      <div className="metric-grid">
        <div className="metric-card data-field"><div className="metric-card-label">Course</div>
          <div className="metric-card-value">{course.total_km} km</div>
          <div className="caption">{course.total_gain_m} m gain · ~{course.estimated_duration_hours} h at your pace</div>
        </div>
        <div className="metric-card data-field"><div className="metric-card-label">Elevation</div>
          <div className="metric-card-value">{course.max_elevation_m} m</div>
          <div className="caption">max (mean {course.mean_elevation_m} m) · altitude keeps {Math.round(derates.altitude_power_fraction * 100)}% of your power</div>
        </div>
        <div className="metric-card data-field"><div className="metric-card-label">Conditions</div>
          <div className="metric-card-value">{conditions.temp_c}°C</div>
          <div className="caption">{conditions.humidity_pct}% RH · heat keeps {Math.round(derates.heat_power_fraction * 100)}% · {conditions.source}</div>
        </div>
        <div className="metric-card data-field"><div className="metric-card-label">CP on the day</div>
          <div className="metric-card-value">{derates.cp_on_the_day_w} W</div>
          <div className="caption">vs {derates.cp_sea_level_fresh_w} W sea-level fresh — both altitude effects modeled (thin air also cuts drag)</div>
        </div>
      </div>

      <h3>What this course asks of you</h3>
      {demands.map((d, i) => (
        <div className="caption" key={i}>• {d.description}</div>
      ))}
      <div className="caption" style={{ opacity: 0.7 }}>{derates.wind}</div>

      <h3>Demand vs you</h3>
      {gap_report.map((g, i) => (
        <div className="adaptive-rec" key={i}>
          <span className={`plan-badge ${GAP_BADGE[g.status]}`}>{g.status}</span>
          <span className="adaptive-rec-text">
            {g.detail}
            {g.confidence === "low" && <span className="caption"> (low-confidence parameter — a hypothesis, not a verdict)</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function RaceView() {
  const [events, setEvents] = useState(null);
  const [selected, setSelected] = useState(null);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: "", date: "", rider_mass_kg: "", bike_kit_kg: "9" });
  const [override, setOverride] = useState({ temp_c: "", humidity_pct: "" });
  const fileRef = useRef(null);

  const load = () => api.listEvents().then(setEvents).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const open = async (event) => {
    setSelected(event);
    setProfile(null);
    try {
      setProfile(await api.eventDemand(event.id));
    } catch {
      setProfile(null);
    }
  };

  const create = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file || !form.name || !form.date || !form.rider_mass_kg) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createEvent(file, form);
      await load();
      setSelected(res.event);
      setProfile(res.profile);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const applyForecast = async () => {
    if (!selected || override.temp_c === "") return;
    setBusy(true);
    try {
      const p = await api.recomputeEvent(selected.id, {
        conditions_override: {
          temp_c: parseFloat(override.temp_c),
          humidity_pct: parseFloat(override.humidity_pct || "50"),
          source: "manual forecast override",
        },
      });
      setProfile(p);
    } finally {
      setBusy(false);
    }
  };

  if (error && !events) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!events) return <div className="loading">Loading events...</div>;

  return (
    <div className="view-grid">
      <h3>Target events</h3>
      <div className="caption">
        Upload a race route (.gpx/.tcx) and the app models what that course will physically demand of you on
        the day — segments, altitude, expected weather — then compares it against your current physiology model.
      </div>

      <div className="model-override-form">
        <input type="file" accept=".gpx,.tcx" ref={fileRef} />
        <input type="text" placeholder="Event name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
        <input type="number" placeholder="Your race weight (kg)" value={form.rider_mass_kg} onChange={(e) => setForm({ ...form, rider_mass_kg: e.target.value })} />
        <input type="number" placeholder="Bike + kit (kg)" value={form.bike_kit_kg} onChange={(e) => setForm({ ...form, bike_kit_kg: e.target.value })} />
        <button className="followup-btn" onClick={create} disabled={busy}>
          {busy ? "Modeling course..." : "Add event & model demands"}
        </button>
      </div>
      {error && <div className="error-box">{error}</div>}

      {events.length > 0 && (
        <div className="followup-row">
          {events.map((e) => (
            <button key={e.id} className={`followup-btn ${selected?.id === e.id ? "active" : ""}`} onClick={() => open(e)}>
              {e.name} ({e.date}){e.gap_summary?.includes("gap") ? " ⚠️" : ""}
            </button>
          ))}
        </div>
      )}

      {selected && (
        <>
          <div className="calendar-nav">
            <h3>{selected.name} — {selected.date}</h3>
            <div style={{ display: "flex", gap: 6 }}>
              <button className="followup-btn" onClick={async () => setProfile(await api.recomputeEvent(selected.id, {}))} disabled={busy}>
                Recompute
              </button>
              <button
                className="followup-btn danger-btn"
                onClick={async () => {
                  if (!window.confirm(`Delete "${selected.name}" and its demand profile?`)) return;
                  await api.deleteEvent(selected.id);
                  setSelected(null);
                  setProfile(null);
                  load();
                }}
              >
                Delete
              </button>
            </div>
          </div>

          <div className="calendar-nav">
            <span className="caption">Forecast override (as race day nears):</span>
            <input type="number" placeholder="°C" style={{ width: 70 }} value={override.temp_c} onChange={(e) => setOverride({ ...override, temp_c: e.target.value })} />
            <input type="number" placeholder="%RH" style={{ width: 70 }} value={override.humidity_pct} onChange={(e) => setOverride({ ...override, humidity_pct: e.target.value })} />
            <button className="followup-btn" onClick={applyForecast} disabled={busy || override.temp_c === ""}>
              Apply forecast
            </button>
          </div>

          {profile ? <DemandProfile profile={profile} /> : <div className="loading">Loading demand profile...</div>}
        </>
      )}
    </div>
  );
}
