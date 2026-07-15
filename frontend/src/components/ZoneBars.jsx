import { useEffect, useState } from "react";
import { api } from "../api";
import { colors } from "../theme";

// One hue, light -> dark by intensity: this is a sequential scale (zones are
// ordered magnitudes, not unrelated categories), so a rainbow would imply
// distinctions that don't exist. Z7 is the darkest, not a different colour.
const ZONE_SHADES = ["#cde2fb", "#9dc5f5", "#6aa6ea", "#3d84d9", "#2a78d6", "#1f5aa8", "#184f95"];

function ZoneTable({ title, block }) {
  const rows = block.rows.filter((r) => r.seconds > 0);
  if (!rows.length) return null;
  return (
    <div className="zone-block">
      <div className="caption">
        {title} — vs {block.reference}
      </div>
      {rows.map((r, i) => (
        <div className="zone-row" key={r.zone}>
          <span className="zone-name">{r.zone}</span>
          <span className="zone-track">
            <span
              className="zone-fill"
              style={{ width: `${r.pct}%`, background: ZONE_SHADES[Math.min(i, ZONE_SHADES.length - 1)] }}
            />
          </span>
          <span className="zone-value">
            {r.minutes}min <span className="zone-pct">{r.pct}%</span>
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ZoneBars({ activity }) {
  const [zones, setZones] = useState(null);

  useEffect(() => {
    setZones(null);
    api
      .activityZones(activity.activity_id)
      .then(setZones)
      .catch(() => setZones({ power: null, hr: null, reason: "Couldn't load zones for this ride." }));
  }, [activity.activity_id]);

  if (!zones) return <div className="loading">Calculating time in zone...</div>;
  if (!zones.power && !zones.hr) return <div className="empty-note">{zones.reason}</div>;

  return (
    <div className="zone-bars">
      {zones.power && <ZoneTable title="Power zones" block={zones.power} />}
      {zones.hr && <ZoneTable title="Heart-rate zones" block={zones.hr} />}
      {!zones.power && zones.hr && (
        <div className="caption">
          No power zones — this ride has no power data. Outdoor power arrives with the meter (~Aug 2026).
        </div>
      )}
    </div>
  );
}
