import { useEffect, useState } from "react";
import { api } from "../api";

// F8: the week as a controller, not a calendar. Shows what reflow changed (one
// line each) and lets the athlete pin days so reflow plans around them.

export default function ReflowPanel() {
  const [reflow, setReflow] = useState(null);

  const load = () => api.planReflow().then(setReflow).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  if (!reflow) return null;

  const togglePin = async (day) => {
    const reason = day.pinned ? "" : window.prompt("Why pin this day? (optional)") || "";
    await api.setPin({ date: day.date, pinned: !day.pinned, reason });
    load();
  };

  const moved = reflow.changes.some((c) => !c.startsWith("Week is on track"));

  return (
    <div className={`adaptive-rec ${moved ? "adaptive-rec-actionable" : ""}`} style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ fontSize: 13 }}>Week reflow</strong>
        <span className="caption">pin a day to keep reflow off it</span>
      </div>
      {reflow.changes.map((c, i) => (
        <div className="adaptive-rec-text" key={i}>
          {c}
        </div>
      ))}
      <div className="followup-row">
        {reflow.week.map((d) => (
          <button
            key={d.date}
            className={`followup-btn ${d.pinned ? "active" : ""}`}
            onClick={() => togglePin(d)}
            disabled={d.in_past}
            title={
              d.pinned
                ? `Pinned${reflow.inputs_snapshot.pins[d.date] ? `: ${reflow.inputs_snapshot.pins[d.date]}` : ""} — click to unpin`
                : d.in_past
                  ? "In the past"
                  : "Click to pin"
            }
          >
            {d.pinned ? "📌 " : ""}
            {d.day_name.slice(0, 3)}
            {d.moved_from ? " ←" : ""}
            {d.blocked ? " ✈️" : ""}
          </button>
        ))}
      </div>
    </div>
  );
}
