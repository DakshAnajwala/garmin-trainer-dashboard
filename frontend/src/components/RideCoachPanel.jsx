import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { colors } from "../theme";

export default function RideCoachPanel({ activity }) {
  const [decoupling, setDecoupling] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [debrief, setDebrief] = useState("");
  const [debriefSaved, setDebriefSaved] = useState(true);
  const [debriefSaving, setDebriefSaving] = useState(false);
  // The initial GET can resolve after the user has already started typing
  // (slow network, or React StrictMode double-invoking the effect in dev).
  // Without this guard, that late response silently overwrites what they
  // typed, and the next blur then saves the overwritten (often empty) value
  // — a real data-loss bug caught by testing, not hypothetical.
  const editedRef = useRef(false);

  useEffect(() => {
    setDecoupling(null);
    setAnalysis(null);
    setError(null);
    setDebrief("");
    setDebriefSaved(true);
    editedRef.current = false;
    api
      .activityDecoupling(activity.activity_id)
      .then(setDecoupling)
      .catch(() => setDecoupling({ available: false, reason: "Couldn't compute decoupling for this ride." }));
    api
      .getRideDebrief(activity.activity_id)
      .then((r) => {
        if (!editedRef.current) setDebrief(r.text || "");
      })
      .catch(() => {});
  }, [activity.activity_id]);

  const saveDebrief = async () => {
    setDebriefSaving(true);
    try {
      await api.saveRideDebrief(activity.activity_id, debrief);
      setDebriefSaved(true);
    } finally {
      setDebriefSaving(false);
    }
  };

  const analyze = async () => {
    setBusy(true);
    setError(null);
    try {
      if (!debriefSaved) await saveDebrief(); // analysis reads the saved debrief server-side
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

      <div className="debrief-box">
        <label className="metric-card-label" htmlFor="ride-debrief">
          How did it feel? (optional — the coach reconciles this against the power/HR data)
        </label>
        <textarea
          id="ride-debrief"
          rows={2}
          value={debrief}
          placeholder="e.g. legs felt flat on the third climb..."
          onChange={(e) => {
            editedRef.current = true;
            setDebrief(e.target.value);
            setDebriefSaved(false);
          }}
          onBlur={() => !debriefSaved && saveDebrief()}
        />
        {!debriefSaved && <span className="caption">{debriefSaving ? "Saving..." : "Unsaved"}</span>}
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
