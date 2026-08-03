import { useEffect, useState } from "react";
import { api } from "../api";

// The club's 300km/week floor — separate from Saturday's team ride, which is
// a single non-negotiable session, not the whole week's volume. Never shown
// anywhere before; this is the one place it's tracked.
export default function WeeklyDistanceCompliance() {
  const [c, setC] = useState(null);

  useEffect(() => {
    api.planCompliance().then(setC).catch(() => {});
  }, []);

  if (!c) return null;

  const pct = Math.min(100, Math.round((c.distance_km / c.target_km) * 100));
  const tone = c.met ? "good" : c.on_pace ? "blue" : "warning";

  return (
    <div className="compliance-widget">
      <div className="compliance-top">
        <strong style={{ fontSize: 13 }}>Weekly distance</strong>
        <span className="caption">
          {c.distance_km} / {c.target_km} km{c.days_remaining > 0 ? ` · ${c.days_remaining}d left` : ""}
        </span>
      </div>
      <div className="compliance-bar">
        <div className={`compliance-bar-fill compliance-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      {!c.met && (
        <div className="caption">
          {c.on_pace
            ? `On pace — ${c.remaining_km} km to go.`
            : `Behind pace — ${c.remaining_km} km to go in ${c.days_remaining} day(s).`}
        </div>
      )}
    </div>
  );
}
