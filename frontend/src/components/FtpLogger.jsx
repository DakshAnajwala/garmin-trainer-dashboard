import { useState } from "react";
import { api } from "../api";

// Logs a new 20-min test result; FTP = 0.95 x that (project convention).
export default function FtpLogger({ currentFtp, onLogged }) {
  const [value, setValue] = useState(231);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.logFtp(parseFloat(value));
      onLogged?.();
    } finally {
      setSaving(false);
    }
  };

  const projectedFtp = Math.round(parseFloat(value || 0) * 0.95 * 10) / 10;

  return (
    <div className="ftp-logger">
      <div className="ftp-current">
        <div className="metric-card-label">Current FTP</div>
        <div className="metric-card-value">{currentFtp?.ftp_watts ? `${currentFtp.ftp_watts} W` : "—"}</div>
        {currentFtp?.source && (
          <div className="metric-card-help">
            {currentFtp.source === "manual" ? `from your test ${currentFtp.date}` : "Garmin estimate (no manual test yet)"}
          </div>
        )}
      </div>
      <div className="ftp-log-form">
        <label>
          Log a new 20-min test (W)
          <input type="number" step="1" min="50" max="600" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <div className="ftp-projected">→ FTP {projectedFtp} W (0.95×)</div>
        <button onClick={save} disabled={saving}>
          {saving ? "Saving..." : "Save test"}
        </button>
      </div>
    </div>
  );
}
