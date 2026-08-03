import { useEffect, useState } from "react";
import "./App.css";
import { api } from "./api";
import { RedactProvider, useRedact } from "./redactContext";
import { UnitsProvider } from "./unitsContext";
import { AuthProvider, useAuth } from "./authContext";
import LoginView from "./views/LoginView";
import ReadinessView from "./views/ReadinessView";
import PowerView from "./views/PowerView";
import TrendsView from "./views/TrendsView";
import PlanView from "./views/PlanView";
import CoachView from "./views/CoachView";
import WorkoutsView from "./views/WorkoutsView";
import WorkoutBuilderView from "./views/WorkoutBuilderView";
import CalendarView from "./views/CalendarView";
import AthleteView from "./views/AthleteView";
import SettingsView from "./views/SettingsView";
import RaceView from "./views/RaceView";
import UndoPanel from "./components/UndoPanel";

const TABS = [
  { key: "readiness", label: "Readiness" },
  { key: "plan", label: "Plan" },
  { key: "calendar", label: "Calendar" },
  { key: "power", label: "Power" },
  { key: "trends", label: "Trends" },
  { key: "workouts", label: "History" },
  { key: "builder", label: "Builder" },
  { key: "athlete", label: "Athlete" },
  { key: "race", label: "Race" },
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
  // Settings is separate state, not a tab value. That's what makes closing it
  // land you exactly where you were — the tab was never disturbed. (There's no
  // router here; adding one to solve this would be a bigger change than the
  // problem, since nothing else in the app is URL-addressable either.)
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [ftpWatts, setFtpWatts] = useState(null);
  const { redacted } = useRedact();

  useEffect(() => {
    api
      .overview()
      .then((d) => setFtpWatts(d.current_ftp?.ftp_watts ?? null))
      .catch(() => {});
  }, []);

  const activeLabel = TABS.find((t) => t.key === tab)?.label ?? "";

  return (
    <>
      <div className="app-header">
        <h1>🚴 Training Dashboard</h1>
        {/* Three controls, each earning its place: undo (recovery has to be
            reachable at the moment of the mistake), redact (its whole purpose is
            "someone just walked up to my desk" — must be one click), and the cog
            for everything else. Units moved into Settings: rarely toggled, and a
            control in two places with no reason is just noise. */}
        <div style={{ display: "flex", gap: 8 }}>
          <UndoPanel />
          <RedactToggle />
          <button
            className={`icon-btn ${settingsOpen ? "active" : ""}`}
            onClick={() => setSettingsOpen((v) => !v)}
            aria-label="Settings"
            aria-expanded={settingsOpen}
            title="Settings"
          >
            ⚙️
          </button>
        </div>
      </div>

      {settingsOpen ? (
        <>
          <div className="calendar-nav">
            <button className="followup-btn" onClick={() => setSettingsOpen(false)}>
              ← Back to {activeLabel}
            </button>
            <h3 style={{ margin: 0 }}>Settings</h3>
          </div>
          <SettingsView />
        </>
      ) : (
        <>
          <nav className="nav-tabs">
            {TABS.map((t) => (
              <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
                {t.label}
              </button>
            ))}
          </nav>
          <TabContent tab={tab} redacted={redacted} ftpWatts={ftpWatts} />
        </>
      )}
    </>
  );
}

function TabContent({ tab, redacted, ftpWatts }) {
  return (
    <>
      {tab === "readiness" && <ReadinessView />}
      {tab === "plan" && <PlanView />}
      {tab === "calendar" && <CalendarView />}
      {tab === "power" && <PowerView />}
      {tab === "trends" && <TrendsView />}
      {tab === "workouts" && <WorkoutsView />}
      {tab === "builder" && <WorkoutBuilderView ftpWatts={redacted ? null : ftpWatts} />}
      {tab === "athlete" && <AthleteView />}
      {tab === "race" && (redacted ? <div className="empty-note">Race demand modeling shows raw power numbers — hidden in Redacted Mode.</div> : <RaceView />)}
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
      <UnitsProvider>
        <AppInner />
      </UnitsProvider>
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
