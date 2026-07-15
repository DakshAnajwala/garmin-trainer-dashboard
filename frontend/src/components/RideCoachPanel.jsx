import { useEffect, useState } from "react";
import { api } from "../api";
import { colors } from "../theme";

export default function RideCoachPanel({ activity }) {
  const [decoupling, setDecoupling] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDecoupling(null);
    setAnalysis(null);
    setError(null);
    api
      .activityDecoupling(activity.activity_id)
      .then(setDecoupling)
      .catch(() => setDecoupling({ available: false, reason: "Couldn't compute decoupling for this ride." }));
  }, [activity.activity_id]);

  const analyze = async () => {
    setBusy(true);
    setError(null);
    try {
      const { reply } = await api.analyzeRide(activity.activity_id);
      setAnalysis(reply);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ride-coach">
      <div className="metric-card">
        <div className="metric-card-label">Aerobic decoupling</div>
        {decoupling === null ? (
          <div className="caption">Calculating...</div>
        ) : decoupling.available ? (
          <>
            <div className="metric-card-value" style={{ color: decoupling.good ? colors.good : colors.warning }}>
              {decoupling.decoupling_pct}%
            </div>
            <div className="caption">
              Pw:Hr {decoupling.first_half_pw_hr} → {decoupling.second_half_pw_hr} (first half → second half).{" "}
              {decoupling.good
                ? `Under ${decoupling.threshold_pct}% — aerobically durable for this duration.`
                : `Over ${decoupling.threshold_pct}% — heart rate drifted up relative to power.`}
            </div>
          </>
        ) : (
          <>
            <div className="metric-card-value" style={{ color: colors.muted }}>—</div>
            <div className="caption">{decoupling.reason}</div>
          </>
        )}
      </div>

      <button className="primary-btn" onClick={analyze} disabled={busy}>
        {busy ? "Analyzing..." : "🔍 Analyze this ride with AI coach"}
      </button>
      {error && <div className="error-box">{error}</div>}
      {analysis && (
        <div className="chat-message assistant" style={{ maxWidth: "100%" }}>
          <div className="chat-role">Coach</div>
          <div className="chat-content">{analysis}</div>
        </div>
      )}
    </div>
  );
}
