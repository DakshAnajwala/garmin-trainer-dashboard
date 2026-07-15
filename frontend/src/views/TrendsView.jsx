import { useEffect, useState } from "react";
import { api } from "../api";
import HrvTrendChart from "../components/HrvTrendChart";
import ReadinessTrendChart from "../components/ReadinessTrendChart";
import PmcChart from "../components/PmcChart";
import TimeRangePicker from "../components/TimeRangePicker";
import { toIsoDateLocal } from "../dateUtils";
import { useRedact } from "../redactContext";

const PMC_PRESETS = [
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "42d", days: 42 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
];

const EXTRAPOLATE_OPTIONS = [
  { label: "None", days: 0 },
  { label: "+7d", days: 7 },
  { label: "+14d", days: 14 },
];

function defaultRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return { start: toIsoDateLocal(start), end: toIsoDateLocal(end) };
}

function pmcDefaultRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 42);
  return { start: toIsoDateLocal(start), end: toIsoDateLocal(end) };
}

export default function TrendsView() {
  const { redacted } = useRedact();
  const [range, setRange] = useState(defaultRange);
  const [hrv, setHrv] = useState(null);
  const [readiness, setReadiness] = useState(null);
  const [error, setError] = useState(null);

  const [intervalsConfigured, setIntervalsConfigured] = useState(null);
  const [pmcRange, setPmcRange] = useState(pmcDefaultRange);
  const [pmc, setPmc] = useState(null);
  const [pmcError, setPmcError] = useState(null);
  const [extrapolateDays, setExtrapolateDays] = useState(0);
  const [activitiesByDate, setActivitiesByDate] = useState({});
  const [prMarkers, setPrMarkers] = useState({});

  useEffect(() => {
    setError(null);
    setHrv(null);
    setReadiness(null);
    Promise.all([api.hrvHistory(range), api.readinessHistory(range)])
      .then(([h, r]) => {
        setHrv(h);
        setReadiness(r);
      })
      .catch((e) => setError(e.message));
  }, [range]);

  useEffect(() => {
    api.intervalsStatus().then((s) => setIntervalsConfigured(s.configured));
  }, []);

  useEffect(() => {
    if (!intervalsConfigured) return;
    setPmcError(null);
    api.intervalsWellness(pmcRange).then(setPmc).catch((e) => setPmcError(e.message));
    api.activitiesByDate(pmcRange.start, pmcRange.end).then(setActivitiesByDate).catch(() => {});
    api.prMarkers(pmcRange.start, pmcRange.end).then(setPrMarkers).catch(() => {});
  }, [intervalsConfigured, pmcRange]);

  return (
    <div className="view-grid">
      <TimeRangePicker onChange={setRange} defaultPreset="1M" />

      {error && <div className="error-box">Couldn't reach the backend: {error}</div>}

      {!error && (!hrv || !readiness) && <div className="loading">Pulling history from Garmin...</div>}

      {!error && hrv && readiness && (
        <>
          <h3>
            HRV — rolling baseline ({range.start} to {range.end})
          </h3>
          {redacted ? (
            <div className="empty-note">Hidden in Redacted Mode.</div>
          ) : hrv.filter((r) => r.last_night_avg_ms != null).length >= 2 ? (
            <HrvTrendChart records={hrv} />
          ) : (
            <div className="empty-note">Not enough HRV history in this range.</div>
          )}

          <h3>
            Training Readiness — trend ({range.start} to {range.end})
          </h3>
          {readiness.filter((r) => r.readiness_score != null).length >= 2 ? (
            <ReadinessTrendChart records={readiness} />
          ) : (
            <div className="empty-note">Not enough readiness history in this range.</div>
          )}
        </>
      )}

      <h3>Fitness / Fatigue / Form (intervals.icu)</h3>
      {redacted ? (
        <div className="empty-note">Hidden in Redacted Mode.</div>
      ) : intervalsConfigured === null ? (
        <div className="loading">Checking intervals.icu connection...</div>
      ) : !intervalsConfigured ? (
        <div className="empty-note">
          Not connected yet. Run <code>python -m scripts.set_secrets</code> to add your intervals.icu API key, and set
          <code> INTERVALS_ATHLETE_ID</code> in <code>.env</code>.
        </div>
      ) : (
        <>
          <TimeRangePicker onChange={setPmcRange} defaultPreset="42d" presets={PMC_PRESETS} />
          <div className="range-picker-presets">
            <span className="caption">Extrapolate:</span>
            {EXTRAPOLATE_OPTIONS.map((o) => (
              <button
                key={o.label}
                className={extrapolateDays === o.days ? "range-btn active" : "range-btn"}
                onClick={() => setExtrapolateDays(o.days)}
              >
                {o.label}
              </button>
            ))}
          </div>
          {pmcError ? (
            <div className="error-box">{pmcError}</div>
          ) : !pmc ? (
            <div className="loading">Loading intervals.icu data...</div>
          ) : pmc.length ? (
            <PmcChart records={pmc} extrapolateDays={extrapolateDays} activitiesByDate={activitiesByDate} prMarkers={prMarkers} />
          ) : (
            <div className="empty-note">No wellness data returned for this range.</div>
          )}
        </>
      )}
    </div>
  );
}
