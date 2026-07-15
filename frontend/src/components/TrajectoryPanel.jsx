import { useEffect, useState } from "react";
import { api } from "../api";
import TrajectoryChart from "./TrajectoryChart";
import { useRedact } from "../redactContext";

export default function TrajectoryPanel() {
  const { redacted } = useRedact();
  const [trajectory, setTrajectory] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.trajectory().then(setTrajectory).catch((e) => setError(e.message));
  }, []);

  if (redacted) return <div className="empty-note">Hidden in Redacted Mode.</div>;
  if (error) return <div className="error-box">{error}</div>;
  if (!trajectory) return <div className="loading">Building your trajectory...</div>;
  if (!trajectory.available) return <div className="empty-note">{trajectory.reason}</div>;

  const { milestone, current, low_confidence: lowConfidence } = trajectory;

  return (
    <div className="view-grid">
      <div className={`milestone-banner ${milestone.reached ? "milestone-reached" : lowConfidence ? "milestone-unknown" : ""}`}>
        <div className="milestone-headline">{milestone.message}</div>
        <div className="caption">
          Now: {current.ftp_w}W at {current.weight_kg}kg = {current.wkg} W/kg. Target {trajectory.target_wkg} W/kg ={" "}
          {current.target_watts}W at today's weight — it moves with your weight rather than sitting at a fixed number.
          {trajectory.ftp_slope_w_per_month != null && (
            <> Current rate: {trajectory.ftp_slope_w_per_month > 0 ? "+" : ""}
              {trajectory.ftp_slope_w_per_month}W/month, decaying by half every {trajectory.gain_half_life_months}{" "}
              months — the same training buys fewer watts as you approach your ceiling (~{trajectory.ftp_ceiling_w}W on
              this trajectory).</>
          )}
          {trajectory.weight_trend_available === false && (
            <> Weight is held flat in the projection — only one weigh-in is logged, so there's no trend to fit.</>
          )}
        </div>
      </div>
      <TrajectoryChart trajectory={trajectory} />
    </div>
  );
}
