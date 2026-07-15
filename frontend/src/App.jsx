import { useEffect, useState } from "react";
import "./App.css";
import { api } from "./api";
import { RedactProvider, useRedact } from "./redactContext";
import { AuthProvider, useAuth } from "./authContext";
import LoginView from "./views/LoginView";
import ReadinessView from "./views/ReadinessView";
import OverviewView from "./views/OverviewView";
import TrendsView from "./views/TrendsView";
import PlanView from "./views/PlanView";
import CoachView from "./views/CoachView";
import WorkoutsView from "./views/WorkoutsView";
import WorkoutBuilderView from "./views/WorkoutBuilderView";
import AeroView from "./views/AeroView";
import CalendarView from "./views/CalendarView";
import GearView from "./views/GearView";

const TABS = [
  { key: "readiness", label: "Readiness" },
  { key: "plan", label: "Plan" },
  { key: "calendar", label: "Calendar" },
  { key: "overview", label: "Overview" },
  { key: "trends", label: "Trends" },
  { key: "workouts", label: "History" },
  { key: "builder", label: "Builder" },
  { key: "aero", label: "Aero" },
  { key: "gear", label: "Gear" },
  { key: "coach", label: "Coach" },
];

function RedactToggle() {
  const { redacted, toggle } = useRedact();
  return (
    <button className={`redact-toggle ${redacted ? "active" : ""}`} onClick={toggle}>
      {redacted ? "🙈 Redacted" : "👁️ Showing fitness data"}
    </button>
  );
}

function AppInner() {
  const [tab, setTab] = useState("readiness");
  const [ftpWatts, setFtpWatts] = useState(null);
  const { redacted } = useRedact();
  const { signOut } = useAuth();

  useEffect(() => {
    api
      .overview()
      .then((d) => setFtpWatts(d.current_ftp?.ftp_watts ?? null))
      .catch(() => {});
  }, []);

  return (
    <>
      <div className="app-header">
        <h1>🚴 Training Dashboard</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <RedactToggle />
          <button className="followup-btn" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
      <nav className="nav-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "readiness" && <ReadinessView />}
      {tab === "plan" && <PlanView />}
      {tab === "calendar" && <CalendarView />}
      {tab === "overview" && <OverviewView />}
      {tab === "trends" && <TrendsView />}
      {tab === "workouts" && <WorkoutsView />}
      {tab === "builder" && <WorkoutBuilderView ftpWatts={redacted ? null : ftpWatts} />}
      {tab === "aero" && <AeroView />}
      {tab === "gear" && <GearView />}
      {tab === "coach" && (redacted ? <div className="empty-note">Coach chat is disabled in Redacted Mode (can't guarantee it won't mention hidden numbers).</div> : <CoachView />)}
    </>
  );
}

function Gate() {
  const { user } = useAuth();
  if (user === undefined) return <div className="loading">Checking sign-in...</div>;
  if (user === null) return <LoginView />;
  return (
    <RedactProvider>
      <AppInner />
    </RedactProvider>
  );
}

function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}

export default App;
