import { useEffect, useState } from "react";
import { api } from "../api";
import PowerCurveChart from "../components/PowerCurveChart";
import FtpProgressionChart from "../components/FtpProgressionChart";
import FtpTestReminder from "../components/FtpTestReminder";
import TrajectoryPanel from "../components/TrajectoryPanel";
import WeightTrendChart from "../components/WeightTrendChart";
import TimeRangePicker from "../components/TimeRangePicker";
import FtpLogger from "../components/FtpLogger";
import RiderProfileCard from "../components/RiderProfileCard";
import CogganChart from "../components/CogganChart";
import WeaknessSuggestion from "../components/WeaknessSuggestion";
import GoalSetter from "../components/GoalSetter";
import { toIsoDateLocal } from "../dateUtils";
import { useRedact } from "../redactContext";

function defaultRange() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return { start: toIsoDateLocal(start), end: toIsoDateLocal(end) };
}

export default function OverviewView() {
  const { redacted } = useRedact();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [weightRange, setWeightRange] = useState(defaultRange);
  const [cogganProfile, setCogganProfile] = useState(null);

  useEffect(() => {
    api.overview().then(setData).catch((e) => setError(e.message));
    api.cogganProfile().then(setCogganProfile).catch(() => {});
  }, []);

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!data) return <div className="loading">Loading overview...</div>;

  const filteredWeightHistory = data.weight_history.filter(
    ([date]) => date >= weightRange.start && date <= weightRange.end
  );

  return (
    <div className="view-grid">
      {redacted ? (
        <div className="empty-note">Power curve, FTP, rider phenotype, and Coggan comparison are hidden in Redacted Mode.</div>
      ) : (
        <>
          <h3>Power curve</h3>
          <PowerCurveChart powerCurve={data.power_curve} unverified={data.power_curve_unverified} />
          <div className="caption">Open marker = self-reported as NOT a confirmed max effort.</div>

          <h3>Rider phenotype</h3>
          <RiderProfileCard profile={data.rider_profile} />

          <h3>FTP</h3>
          <FtpTestReminder />
          <FtpLogger currentFtp={data.current_ftp} onLogged={() => api.overview().then(setData)} />

          <h3>FTP progression</h3>
          <FtpProgressionChart
            ftpHistory={data.ftp_history}
            garminFtp={data.garmin_ftp}
            targetWkg={data.target_wkg}
            latestWeight={data.latest_weight}
          />
          {!data.latest_weight && (
            <div className="caption">Log your weight on the Readiness tab to see the dynamic W/kg target line.</div>
          )}

          <h3>Trajectory to {data.target_wkg} W/kg</h3>
          <TrajectoryPanel />

          <h3>Coggan power profile</h3>
          <CogganChart profile={cogganProfile} />
          {cogganProfile?.weakest_zone && <WeaknessSuggestion weakestZone={cogganProfile.weakest_zone} />}

          <h3>Goals</h3>
          <GoalSetter cogganProfile={cogganProfile} />
        </>
      )}

      <h3>Weight trend</h3>
      {redacted ? (
        <div className="empty-note">Hidden in Redacted Mode.</div>
      ) : (
        <>
          <TimeRangePicker onChange={setWeightRange} defaultPreset="1M" />
          {filteredWeightHistory.length >= 2 ? (
            <WeightTrendChart history={filteredWeightHistory} />
          ) : (
            <div className="empty-note">Not enough logged weight in this range yet.</div>
          )}
        </>
      )}
    </div>
  );
}
