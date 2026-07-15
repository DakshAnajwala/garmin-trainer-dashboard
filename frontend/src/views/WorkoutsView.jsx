import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import ActivitySplitsChart from "../components/ActivitySplitsChart";
import ExportPanel from "../components/ExportPanel";
import RideCoachPanel from "../components/RideCoachPanel";
import RouteMap from "../components/RouteMap";
import SegmentAnalyzer from "../components/SegmentAnalyzer";
import ZoneBars from "../components/ZoneBars";
import { useRedact } from "../redactContext";

const TYPE_ICON = {
  road_biking: "🚴",
  indoor_cycling: "🏠",
  cycling: "🚴",
  virtual_ride: "🖥️",
  walking: "🚶",
  running: "🏃",
};

function fmtDuration(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

function fmtDistance(m) {
  return m ? `${(m / 1000).toFixed(1)} km` : "—";
}

export default function WorkoutsView() {
  const { redacted } = useRedact();
  const [activities, setActivities] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [splits, setSplits] = useState(null);
  const [details, setDetails] = useState(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState(null);
  const [showHidden, setShowHidden] = useState(false);
  const [gear, setGear] = useState([]);
  const fileInputRef = useRef(null);

  const loadActivities = (includeHidden = showHidden) =>
    api
      .activities(30, includeHidden)
      .then(setActivities)
      .catch((e) => setError(e.message));

  useEffect(() => {
    loadActivities(showHidden);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showHidden]);

  useEffect(() => {
    api.listGear().then(setGear).catch(() => {});
  }, []);

  const junkCount = (activities || []).filter((a) => a.likely_junk && !a.hidden).length;

  const hideJunk = async () => {
    const { hidden_count: count } = await api.hideJunkActivities();
    if (count) {
      setSelected(null);
      await loadActivities();
      api.listGear().then(setGear).catch(() => {});
    }
  };

  const handleImportFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImportBusy(true);
    setImportError(null);
    try {
      await api.importActivity(file);
      await loadActivities();
    } catch (err) {
      setImportError(err.message);
    } finally {
      setImportBusy(false);
    }
  };

  const openActivity = async (act) => {
    setSelected(act);
    setSplits(null);
    setDetails(null);
    try {
      setSplits(await api.activitySplits(act.activity_id));
    } catch {
      setSplits([]);
    }
    try {
      setDetails(await api.activityDetails(act.activity_id));
    } catch {
      setDetails([]);
    }
  };

  const isImported = (act) => act?.source === "imported";

  const removeActivity = async (act) => {
    const message = isImported(act)
      ? `Permanently delete "${act.name}"? This imported activity isn't stored anywhere else.`
      : `Hide "${act.name}"?\n\nIt stays in Garmin Connect — this only hides it from this dashboard (activity list, calendar, and Fitness/Fatigue tooltip). You can unhide it later.`;
    if (!window.confirm(message)) return;
    await api.deleteActivity(act.activity_id);
    setSelected(null);
    await loadActivities();
    api.listGear().then(setGear).catch(() => {});
  };

  const unhide = async (act) => {
    await api.unhideActivity(act.activity_id);
    await loadActivities();
    api.listGear().then(setGear).catch(() => {});
  };

  const setActivityGear = async (act, gearId) => {
    await api.assignActivityGear(act.activity_id, gearId || null);
    setSelected({ ...act, gear_id: gearId || null, gear_assigned_explicitly: !!gearId });
    await loadActivities();
    api.listGear().then(setGear).catch(() => {});
  };

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!activities) return <div className="loading">Loading your activities...</div>;

  return (
    <div className="view-grid">
      <div className="calendar-nav">
        <h3>Recent activities</h3>
        <input
          type="file"
          accept=".fit,.gpx,.tcx"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleImportFile}
        />
        <button className="followup-btn" onClick={() => fileInputRef.current?.click()} disabled={importBusy}>
          {importBusy ? "Importing..." : "📥 Import .fit/.gpx/.tcx"}
        </button>
        <button className={showHidden ? "followup-btn active" : "followup-btn"} onClick={() => setShowHidden((v) => !v)}>
          {showHidden ? "Hide hidden" : "Show hidden"}
        </button>
      </div>
      {junkCount > 0 && (
        <div className="junk-notice">
          <span>
            {junkCount} {junkCount === 1 ? "ride looks" : "rides look"} like transfers or roll-outs rather than
            training. They still count toward gear mileage and training load.
          </span>
          <button className="followup-btn" onClick={hideJunk}>
            Hide {junkCount === 1 ? "it" : "them all"}
          </button>
        </div>
      )}
      <div className="caption">
        Direct Strava/Wahoo/Zwift sync isn't built (needs a developer app registered with each platform) — export an
        activity file from any of them and import it here instead.
      </div>
      {importError && <div className="error-box">{importError}</div>}
      <div className="activity-list">
        {activities.map((a) => (
          <button
            key={a.activity_id}
            className={`activity-row ${selected?.activity_id === a.activity_id ? "active" : ""} ${a.hidden ? "activity-row-hidden" : ""}`}
            onClick={() => openActivity(a)}
          >
            <span className="activity-icon">{TYPE_ICON[a.type] || "•"}</span>
            <span className="activity-main">
              <span className="activity-name">
                {a.name}
                {a.hidden && <span className="plan-badge badge-muted"> hidden</span>}
                {a.source === "imported" && <span className="plan-badge badge-blue"> imported</span>}
                {a.likely_junk && !a.hidden && <span className="plan-badge badge-warning"> likely not training</span>}
              </span>
              <span className="activity-sub">{a.start_time_local}</span>
            </span>
            <span className="activity-stats">
              <span>{fmtDuration(a.duration_sec)}</span>
              <span>{fmtDistance(a.distance_m)}</span>
              <span>{redacted ? "•••" : a.avg_power_w ? `${a.avg_power_w}W` : a.avg_hr ? `${a.avg_hr}bpm` : "—"}</span>
            </span>
          </button>
        ))}
      </div>

      {selected && (
        <div className="activity-detail">
          <div className="calendar-nav">
            <h3>
              {selected.name} — {selected.start_time_local}
            </h3>
            {selected.hidden ? (
              <button className="followup-btn" onClick={() => unhide(selected)}>
                Unhide
              </button>
            ) : (
              <button className="followup-btn danger-btn" onClick={() => removeActivity(selected)}>
                {isImported(selected) ? "Delete" : "Hide"}
              </button>
            )}
          </div>

          {selected.likely_junk && !selected.hidden && <div className="caption">⚠️ {selected.reason}</div>}

          <div className="gear-picker">
            <span className="caption">Gear:</span>
            <select value={selected.gear_id || ""} onChange={(e) => setActivityGear(selected, e.target.value)}>
              <option value="">— none —</option>
              {gear.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            {selected.gear_id && !selected.gear_assigned_explicitly && (
              <span className="caption">(default for {selected.type} — pick one to override)</span>
            )}
            {gear.length === 0 && <span className="caption">No gear yet — add some on the Gear tab.</span>}
          </div>

          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-card-label">Duration</div>
              <div className="metric-card-value">{fmtDuration(selected.duration_sec)}</div>
            </div>
            <div className="metric-card">
              <div className="metric-card-label">Distance</div>
              <div className="metric-card-value">{fmtDistance(selected.distance_m)}</div>
            </div>
            <div className="metric-card">
              <div className="metric-card-label">Avg / Max HR</div>
              <div className="metric-card-value">
                {selected.avg_hr ?? "—"}
                {selected.max_hr ? ` / ${selected.max_hr}` : ""}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-card-label">Avg / Norm power</div>
              <div className="metric-card-value">
                {redacted
                  ? "•••"
                  : `${selected.avg_power_w ? `${selected.avg_power_w}W` : "—"}${selected.norm_power_w ? ` / ${selected.norm_power_w}W` : ""}`}
              </div>
            </div>
          </div>
          {!selected.avg_power_w && (
            <div className="caption">No power data (outdoor ride — power meter arrives ~August 2026).</div>
          )}
          <h3>Time in zone</h3>
          <ZoneBars activity={selected} />

          {!redacted && <RideCoachPanel activity={selected} />}

          <h3>Route</h3>
          {details === null ? (
            <div className="loading">Loading route...</div>
          ) : (
            <RouteMap samples={details} />
          )}

          {splits === null ? (
            <div className="loading">Loading splits...</div>
          ) : splits.length ? (
            <ActivitySplitsChart splits={splits} />
          ) : (
            <div className="empty-note">No lap splits for this activity.</div>
          )}

          <h3>Select a segment</h3>
          {details === null ? (
            <div className="loading">Loading ride detail...</div>
          ) : details.length ? (
            <SegmentAnalyzer samples={details} />
          ) : (
            <div className="empty-note">No detailed sample data for this activity.</div>
          )}
        </div>
      )}

      <ExportPanel />
    </div>
  );
}
