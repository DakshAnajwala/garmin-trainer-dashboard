import { api } from "../api";
import PowerCurveChart from "../components/PowerCurveChart";
import FtpProgressionChart from "../components/FtpProgressionChart";
import FtpTestReminder from "../components/FtpTestReminder";
import TrajectoryPanel from "../components/TrajectoryPanel";
import FtpLogger from "../components/FtpLogger";
import CogganChart from "../components/CogganChart";
import WeaknessSuggestion from "../components/WeaknessSuggestion";
import GoalSetter from "../components/GoalSetter";
import { useCachedApi } from "../useCachedApi";
import { useRedact } from "../redactContext";

// Everything on this page answers one question: how much power can you make,
// and how does that compare?
//
// It was "Overview", which meant "everything that didn't fit elsewhere" — and
// it had grown to eleven unrelated components. The weight-trend chart moved out
// to Readiness, where the rest of the body metrics live; weight still appears
// here, but only where it earns its place as the denominator of W/kg.
//
// Order is deliberate: what you can do now (curve), how that ranks (profile),
// what you're measured against (FTP), and where you're heading (trajectory,
// goals). Rider phenotype moved to Athlete — "what kind of rider am I" is
// identity, not output.

export default function PowerView() {
  const { redacted } = useRedact();

  const {
    data,
    error,
    loading,
    refreshing,
    refresh,
  } = useCachedApi("overview", api.overview);
  const { data: cogganProfile } = useCachedApi("coggan-profile", api.cogganProfile);

  // Nothing cached and nothing fetched yet — the only time a spinner is honest.
  if (loading && error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (loading) return <div className="loading">Loading your power data...</div>;

  return (
    <div className="view-grid">
      <div className="calendar-nav">
        <h3 style={{ margin: 0 }}>Power</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Stale data is shown immediately and corrected in place; say so
              rather than letting numbers change under the reader silently. */}
          {refreshing && <span className="caption">refreshing…</span>}
          <button className="followup-btn" onClick={refresh} disabled={refreshing}>
            Refresh
          </button>
        </div>
      </div>

      {/* A failed refresh keeps the cached numbers on screen — blanking the
          page because one poll failed would be worse than slightly old data. */}
      {error && <div className="caption">Showing last known data — couldn't refresh: {error}</div>}

      {redacted ? (
        <div className="empty-note">
          Power curve, FTP, and the Coggan comparison are all hidden in Redacted Mode.
        </div>
      ) : (
        <>
          <h3>Power curve</h3>
          <PowerCurveChart powerCurve={data.power_curve} unverified={data.power_curve_unverified} />
          <div className="caption">
            Open marker = self-reported as NOT a confirmed max effort.
            {data.rides_analyzed != null && ` Measured from ${data.rides_analyzed} cached ride(s).`}
          </div>

          <h3>Power profile</h3>
          <CogganChart profile={cogganProfile} />
          {cogganProfile?.weakest_zone && <WeaknessSuggestion weakestZone={cogganProfile.weakest_zone} />}

          <h3>FTP</h3>
          <FtpTestReminder />
          <FtpLogger currentFtp={data.current_ftp} onLogged={refresh} />

          <h3>FTP progression</h3>
          <FtpProgressionChart
            ftpHistory={data.ftp_history}
            garminFtp={data.garmin_ftp}
            targetWkg={data.target_wkg}
            latestWeight={data.latest_weight}
          />
          {!data.latest_weight && (
            <div className="caption">
              Log your weight on the Readiness tab to see the dynamic W/kg target line.
            </div>
          )}

          <h3>Trajectory to {data.target_wkg} W/kg</h3>
          <TrajectoryPanel />

          <h3>Goals</h3>
          <GoalSetter cogganProfile={cogganProfile} />
        </>
      )}
    </div>
  );
}
