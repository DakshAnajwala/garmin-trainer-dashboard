import { useEffect, useState } from "react";
import { api } from "../api";
import { colors } from "../theme";
import ReadinessGauge from "../components/ReadinessGauge";
import VerdictBanner from "../components/VerdictBanner";
import MetricCard from "../components/MetricCard";
import BarChart from "../components/BarChart";
import WeightLogger from "../components/WeightLogger";
import { useRedact } from "../redactContext";

export default function ReadinessView() {
  const { redacted } = useRedact();
  const [data, setData] = useState(null);
  const [weightHistory, setWeightHistory] = useState([]);
  const [prs, setPrs] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    try {
      const [readiness, weights] = await Promise.all([api.readiness(), api.weightHistory(1)]);
      setData(readiness);
      setWeightHistory(weights);
      api.personalRecords().then(setPrs).catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!data) return <div className="loading">Pulling today's Garmin data...</div>;

  const { snapshot, verdict } = data;
  const latestWeight = weightHistory.length ? weightHistory[weightHistory.length - 1][1] : null;
  const ftpWatts = data.current_ftp?.ftp_watts;
  const currentWkg = latestWeight && ftpWatts ? (ftpWatts / latestWeight).toFixed(2) : null;

  return (
    <div className="view-grid">
      <div className="gauge-row">
        <ReadinessGauge score={snapshot.training_readiness?.readiness_score} verdictLabel={verdict.verdict} />
        <VerdictBanner verdict={verdict} />
      </div>
      <div className="caption">Today's schedule: {verdict.scheduled_session}</div>

      <div className="metric-grid">
        <MetricCard
          label="HRV (last night)"
          value={redacted ? "•••" : snapshot.hrv?.last_night_avg_ms ? `${snapshot.hrv.last_night_avg_ms} ms` : null}
          help={redacted ? null : snapshot.hrv ? `7d avg ${snapshot.hrv.weekly_avg_ms}ms, ${snapshot.hrv.status}` : null}
        />
        <MetricCard label="Resting HR" value={snapshot.resting_heart_rate?.resting_hr_bpm ? `${snapshot.resting_heart_rate.resting_hr_bpm} bpm` : null} />
        <MetricCard label="Sleep score" value={snapshot.sleep?.sleep_score} help={snapshot.sleep ? `${snapshot.sleep.total_sleep_seconds ? (snapshot.sleep.total_sleep_seconds / 3600).toFixed(1) : "?"}h` : null} />
        <MetricCard
          label="Body Battery"
          value={snapshot.body_battery?.charged != null ? `+${snapshot.body_battery.charged} / -${snapshot.body_battery.drained}` : null}
        />
        <MetricCard label="Avg stress" value={snapshot.stress?.avg_stress_level} />
        <MetricCard
          label="Breathing rate"
          value={snapshot.respiration?.avg_waking_breaths_per_min ? `${Math.round(snapshot.respiration.avg_waking_breaths_per_min)}/min` : null}
        />
        <MetricCard label="ACWR" value={redacted ? "•••" : snapshot.training_load?.acwr?.toFixed(2)} help={redacted ? null : snapshot.training_load?.status} />
        <MetricCard label="VO2max (cycling)" value={redacted ? "•••" : snapshot.vo2_max?.vo2_max_cycling} />
        <MetricCard
          label="Endurance score"
          value={redacted ? "•••" : (snapshot.endurance_score?.score ?? null)}
          help={redacted ? null : snapshot.endurance_score?.score == null ? "Garmin hasn't populated this yet" : null}
        />
      </div>

      {prs && (
        <>
          <h3>All-time bests (since tracking began)</h3>
          <div className="metric-grid">
            <MetricCard label="Lowest resting HR" value={prs.lowest_rhr ? `${prs.lowest_rhr.value} bpm` : null} help={prs.lowest_rhr?.date} />
            <MetricCard label="Highest HRV" value={redacted ? "•••" : prs.highest_hrv ? `${prs.highest_hrv.value} ms` : null} help={redacted ? null : prs.highest_hrv?.date} />
            <MetricCard label="Highest readiness" value={prs.highest_readiness ? `${prs.highest_readiness.value}/100` : null} help={prs.highest_readiness?.date} />
            <MetricCard label="Highest VO2max" value={redacted ? "•••" : (prs.highest_vo2max?.value ?? null)} help={redacted ? null : prs.highest_vo2max?.date} />
          </div>
        </>
      )}

      <h3>Training load</h3>
      {redacted ? (
        <div className="empty-note">Hidden in Redacted Mode.</div>
      ) : snapshot.training_load?.acute_load != null ? (
        <BarChart
          categories={["Acute", "Chronic"]}
          values={[snapshot.training_load.acute_load, snapshot.training_load.chronic_load]}
          colorList={[colors.blue, "#1baf7a"]}
          height={220}
        />
      ) : (
        <div className="empty-note">No training load data for today.</div>
      )}

      <h3>Weight & W/kg</h3>
      <div className="weight-row">
        {redacted ? (
          <div className="empty-note">Weight and W/kg are hidden in Redacted Mode.</div>
        ) : (
          <>
            <WeightLogger latestWeight={latestWeight} onLogged={load} />
            {latestWeight ? (
              <div className="metric-grid">
                <MetricCard label="Latest weight" value={`${latestWeight} kg`} />
                <MetricCard
                  label="Current W/kg"
                  value={currentWkg}
                  help={ftpWatts ? `FTP ${ftpWatts}W (${data.current_ftp.source === "manual" ? "manual test" : "Garmin est."})` : "no FTP yet"}
                />
              </div>
            ) : (
              <div className="empty-note">Log your weight to start tracking W/kg.</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
