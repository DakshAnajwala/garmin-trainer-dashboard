import { useEffect, useState } from "react";
import { api } from "../api";
import { toIsoDateLocal } from "../dateUtils";
import { useRedact } from "../redactContext";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const PLANNED_COLOR = {
  rest: "var(--text-muted)",
  rest_swap: "var(--text-muted)",
  endurance: "var(--blue)",
  endurance_swap: "var(--blue)",
  intervals: "var(--warning)",
  team_ride: "var(--good)",
  long_ride: "var(--serious, #ec835a)",
};

const TYPE_ICON = {
  road_biking: "🚴",
  indoor_cycling: "🏠",
  cycling: "🚴",
  virtual_ride: "🖥️",
  walking: "🚶",
  running: "🏃",
};

// Monday-first grid, matching the backend's date.weekday() convention (0=Mon).
function mondayOnOrBefore(d) {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7; // JS getDay() is Sun=0 — shift to Mon=0
  out.setDate(out.getDate() - dow);
  return out;
}

function sundayOnOrAfter(d) {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7;
  out.setDate(out.getDate() + (6 - dow));
  return out;
}

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export default function CalendarView() {
  const { redacted } = useRedact();
  const [monthDate, setMonthDate] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });
  const [data, setData] = useState({});
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const monthStart = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
  const monthEnd = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0);
  const gridStart = mondayOnOrBefore(monthStart);
  const gridEnd = sundayOnOrAfter(monthEnd);

  useEffect(() => {
    setError(null);
    setSelected(null);
    api
      .calendar(toIsoDateLocal(gridStart), toIsoDateLocal(gridEnd))
      .then(setData)
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthDate]);

  const days = [];
  for (let d = new Date(gridStart); d <= gridEnd; d.setDate(d.getDate() + 1)) {
    days.push(new Date(d));
  }

  const todayIso = toIsoDateLocal(new Date());

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;

  return (
    <div className="view-grid">
      <div className="calendar-nav">
        <button className="followup-btn" onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() - 1, 1))}>
          ← Prev
        </button>
        <h3>{monthDate.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h3>
        <button className="followup-btn" onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 1))}>
          Next →
        </button>
        <button className="followup-btn" onClick={() => setMonthDate(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
          Today
        </button>
      </div>

      <div className="calendar-grid">
        {WEEKDAY_LABELS.map((l) => (
          <div key={l} className="calendar-header">
            {l}
          </div>
        ))}
        {days.map((d) => {
          const iso = toIsoDateLocal(d);
          const inMonth = d.getMonth() === monthDate.getMonth();
          const cell = data[iso];
          const planned = cell?.planned;
          const activities = cell?.activities || [];
          return (
            <button
              key={iso}
              className={`calendar-cell ${inMonth ? "" : "calendar-cell-muted"} ${iso === todayIso ? "calendar-cell-today" : ""} ${selected === iso ? "calendar-cell-selected" : ""}`}
              onClick={() => setSelected(iso)}
            >
              <span className="calendar-day-num">{d.getDate()}</span>
              {planned && (
                <span
                  className="calendar-chip calendar-chip-planned"
                  style={{ background: PLANNED_COLOR[planned.session_type] || "var(--text-muted)" }}
                  title={planned.title}
                >
                  {planned.title}
                </span>
              )}
              {activities.map((a) => (
                <span key={a.activity_id} className="calendar-chip calendar-chip-activity">
                  {TYPE_ICON[a.type] || "•"} {a.name}
                </span>
              ))}
            </button>
          );
        })}
      </div>

      {selected && data[selected] && (
        <div className="activity-detail">
          <h3>{selected}</h3>
          {data[selected].planned ? (
            <div className="plan-card plan-card-active">
              <div className="plan-card-title">{data[selected].planned.title}</div>
              <div className="plan-card-detail">{data[selected].planned.detail}</div>
              {data[selected].planned.duration_min && (
                <div className="plan-card-meta">{data[selected].planned.duration_min} min</div>
              )}
            </div>
          ) : (
            <div className="empty-note">No planned session.</div>
          )}
          {data[selected].activities.length === 0 ? (
            <div className="empty-note">No completed activities this day.</div>
          ) : (
            <div className="activity-list">
              {data[selected].activities.map((a) => (
                <div key={a.activity_id} className="activity-row">
                  <span className="activity-icon">{TYPE_ICON[a.type] || "•"}</span>
                  <span className="activity-main">
                    <span className="activity-name">{a.name}</span>
                    <span className="activity-sub">{a.start_time_local}</span>
                  </span>
                  <span className="activity-stats">
                    <span>{fmtDuration(a.duration_sec)}</span>
                    <span>{redacted ? "•••" : a.avg_power_w ? `${a.avg_power_w}W` : a.avg_hr ? `${a.avg_hr}bpm` : "—"}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
