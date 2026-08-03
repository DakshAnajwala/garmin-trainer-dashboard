import { useEffect, useState } from "react";
import { api } from "../api";
import CoachPlanModal from "../components/CoachPlanModal";
import PlannedWorkoutModal from "../components/PlannedWorkoutModal";
import TodaySuggestionPanel from "../components/TodaySuggestionPanel";
import { toIsoDateLocal } from "../dateUtils";
import { useRedact } from "../redactContext";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const PLANNED_COLOR = {
  rest: "var(--text-muted)",
  rest_swap: "var(--text-muted)",
  endurance: "var(--blue)",
  endurance_swap: "var(--blue)",
  intervals: "var(--warning)",
  team_ride: "var(--good)",
  long_ride: "var(--serious, #ec835a)",
};

const TYPE_ICON = {
  road_biking: "🚴",
  indoor_cycling: "🏠",
  cycling: "🚴",
  virtual_ride: "🖥️",
  walking: "🚶",
  running: "🏃",
};

// Monday-first grid, matching the backend's date.weekday() convention (0=Mon).
function mondayOnOrBefore(d) {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7; // JS getDay() is Sun=0 — shift to Mon=0
  out.setDate(out.getDate() - dow);
  return out;
}

function sundayOnOrAfter(d) {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7;
  out.setDate(out.getDate() + (6 - dow));
  return out;
}

function fmtDuration(sec) {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
}

export default function CalendarView() {
  const { redacted } = useRedact();
  const [monthDate, setMonthDate] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d;
  });
  const [data, setData] = useState({});
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ftpWatts, setFtpWatts] = useState(null);
  const [modalDate, setModalDate] = useState(null); // which planned day's edit modal is open
  const [coachPlanDate, setCoachPlanDate] = useState(null); // which day's "let my coach plan" is open
  const [libraryOpenFor, setLibraryOpenFor] = useState(null); // which day's "add from library" picker is open
  const [suggestFor, setSuggestFor] = useState(null); // which day's "what should I do?" panel is open
  const [library, setLibrary] = useState([]);

  useEffect(() => {
    api.listWorkouts().then(setLibrary).catch(() => {});
  }, []);

  // FTP so the step editor can show target watts, not just %FTP. Cheap, cached.
  useEffect(() => {
    api.overview().then((d) => setFtpWatts(d.current_ftp?.ftp_watts ?? null)).catch(() => {});
  }, []);

  const monthStart = new Date(monthDate.getFullYear(), monthDate.getMonth(), 1);
  const monthEnd = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0);
  const gridStart = mondayOnOrBefore(monthStart);
  const gridEnd = sundayOnOrAfter(monthEnd);

  const reload = () =>
    api
      .calendar(toIsoDateLocal(gridStart), toIsoDateLocal(gridEnd))
      .then(setData)
      .catch((e) => setError(e.message));

  useEffect(() => {
    setError(null);
    setSelected(null);
    // Clear the day-scoped panels too, or navigating away and back re-opens
    // them on the same date without the athlete having asked.
    setSuggestFor(null);
    setLibraryOpenFor(null);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthDate]);

  // Generate the algorithm's suggestion for the week containing `dayIso`.
  // Non-destructive server-side: days already planned are skipped, so this is
  // safe to click again after editing a day.
  const generateWeek = async (dayIso) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.generateWeek(dayIso);
      await reload();
      if (r.created && Object.keys(r.created).length === 0 && r.skipped?.length) {
        setError("That week is already planned — clear a day first to regenerate it.");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // "Add a workout": drop a blank structured session on the day and open it
  // straight into the edit modal — building it IS the point, not naming it first.
  const addBlankWorkout = async (dayIso) => {
    setBusy(true);
    try {
      await api.savePlanned(dayIso, {
        session_type: "custom", title: "New workout", detail: "", source: "custom",
        steps: [{ duration_sec: 300, target_type: "steady", target_low_pct_ftp: 0.75 }],
      });
      await reload();
      setModalDate(dayIso);
    } finally {
      setBusy(false);
    }
  };

  const addFromLibrary = async (dayIso, savedWorkout) => {
    setBusy(true);
    try {
      await api.savePlanned(dayIso, {
        session_type: "custom",
        title: savedWorkout.name,
        detail: savedWorkout.description || "",
        source: "custom",
        steps: savedWorkout.steps,
      });
      setLibraryOpenFor(null);
      await reload();
    } finally {
      setBusy(false);
    }
  };

  const savePlanned = async (dayIso, workout) => {
    await api.savePlanned(dayIso, workout);
    await reload();
  };

  const confirmCoachPlan = async (dayIso, workout) => {
    await api.savePlanned(dayIso, workout);
    setCoachPlanDate(null);
    await reload();
  };

  const deletePlanned = async (dayIso) => {
    await api.clearPlanned(dayIso);
    setModalDate(null);
    await reload();
  };

  const hasAnyPlanned = Object.values(data).some((c) => c?.planned);

  const days = [];
  for (let d = new Date(gridStart); d <= gridEnd; d.setDate(d.getDate() + 1)) {
    days.push(new Date(d));
  }

  const todayIso = toIsoDateLocal(new Date());

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;

  return (
    <div className="view-grid">
      <div className="calendar-nav">
        <button className="followup-btn" onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() - 1, 1))}>
          ← Prev
        </button>
        <h3>{monthDate.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h3>
        <button className="followup-btn" onClick={() => setMonthDate(new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 1))}>
          Next →
        </button>
        <button className="followup-btn" onClick={() => setMonthDate(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>
          Today
        </button>
        <button className="followup-btn" onClick={() => generateWeek(todayIso)} disabled={busy}>
          {busy ? "Generating…" : "✨ Generate this week"}
        </button>
      </div>

      {!hasAnyPlanned && (
        <div className="caption">
          Your calendar is empty. Use <strong>Generate this week</strong> to fill it with a suggested plan, or
          click any day to add your own session. Nothing is planned until you choose to.
        </div>
      )}

      <div className="calendar-grid">
        {WEEKDAY_LABELS.map((l) => (
          <div key={l} className="calendar-header">
            {l}
          </div>
        ))}
        {days.map((d) => {
          const iso = toIsoDateLocal(d);
          const inMonth = d.getMonth() === monthDate.getMonth();
          const cell = data[iso];
          const planned = cell?.planned;
          const activities = cell?.activities || [];
          return (
            <div
              key={iso}
              role="button"
              tabIndex={0}
              className={`calendar-cell ${inMonth ? "" : "calendar-cell-muted"} ${iso === todayIso ? "calendar-cell-today" : ""} ${selected === iso ? "calendar-cell-selected" : ""}`}
              onClick={() => setSelected(iso)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setSelected(iso)}
            >
              <span className="calendar-day-num">{d.getDate()}</span>
              {planned && (
                // Clicking the workout opens the edit/delete modal directly;
                // stopPropagation so it doesn't also just select the day.
                <button
                  className="calendar-chip calendar-chip-planned"
                  style={{ background: PLANNED_COLOR[planned.session_type] || "var(--text-muted)" }}
                  title={`${planned.title} — click to edit`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelected(iso);
                    setModalDate(iso);
                  }}
                >
                  {planned.title}
                </button>
              )}
              {activities.map((a) => (
                <span key={a.activity_id} className="calendar-chip calendar-chip-activity">
                  {TYPE_ICON[a.type] || "•"} {a.name}
                </span>
              ))}
            </div>
          );
        })}
      </div>

      {selected && data[selected] && (
        <div className="activity-detail">
          <h3>{selected}</h3>
          {data[selected].planned ? (
            <button className="plan-card plan-card-active plan-card-clickable" onClick={() => setModalDate(selected)}>
              <div className="plan-card-top">
                <span className="plan-card-title">{data[selected].planned.title}</span>
                <span className={`plan-badge ${data[selected].planned.source === "custom" ? "badge-blue" : "badge-muted"}`}>
                  {data[selected].planned.source === "custom" ? "your session" : "suggested"}
                </span>
              </div>
              <div className="plan-card-detail">{data[selected].planned.detail}</div>
              {data[selected].planned.duration_min && (
                <div className="plan-card-meta">{data[selected].planned.duration_min} min</div>
              )}
              <div className="caption">
                {data[selected].planned.steps?.length > 0
                  ? `${data[selected].planned.steps.length} structured steps · click to view, edit or delete`
                  : "Click to edit or delete"}
              </div>
            </button>
          ) : (
            <div className="day-menu">
              <div className="caption">No planned session — what would you like to do?</div>
              <div className="day-menu-options">
                <button
                  className="primary-btn"
                  onClick={() => setSuggestFor(suggestFor === selected ? null : selected)}
                  disabled={busy}
                >
                  🧠 What should I do{selected === todayIso ? " today" : ""}?
                </button>
                <button className="followup-btn" onClick={() => addBlankWorkout(selected)} disabled={busy}>
                  📝 Add a workout
                </button>
                <button
                  className="followup-btn"
                  onClick={() => setLibraryOpenFor(libraryOpenFor === selected ? null : selected)}
                  disabled={busy || library.length === 0}
                  title={library.length === 0 ? "No saved workouts yet — build one in the Builder tab" : undefined}
                >
                  📚 Add from my library
                </button>
                <button className="followup-btn" onClick={() => setCoachPlanDate(selected)} disabled={busy}>
                  🧠 Let my coach plan for me
                </button>
                <button className="followup-btn" onClick={() => generateWeek(selected)} disabled={busy}>
                  ✨ Generate this week
                </button>
              </div>

              {libraryOpenFor === selected && (
                <div className="day-menu-library">
                  {library.map((w) => (
                    <button key={w.id} className="followup-btn" onClick={() => addFromLibrary(selected, w)} disabled={busy}>
                      {w.name} ({w.steps.length} steps)
                    </button>
                  ))}
                </div>
              )}

              {suggestFor === selected && (
                <TodaySuggestionPanel
                  date={selected}
                  ftpWatts={redacted ? null : ftpWatts}
                  onAdded={async () => {
                    setSuggestFor(null);
                    await reload();
                  }}
                />
              )}
            </div>
          )}
          {data[selected].activities.length === 0 ? (
            <div className="empty-note">No completed activities this day.</div>
          ) : (
            <div className="activity-list">
              {data[selected].activities.map((a) => (
                <div key={a.activity_id} className="activity-row">
                  <span className="activity-icon">{TYPE_ICON[a.type] || "•"}</span>
                  <span className="activity-main">
                    <span className="activity-name">{a.name}</span>
                    <span className="activity-sub">{a.start_time_local}</span>
                  </span>
                  <span className="activity-stats">
                    <span>{fmtDuration(a.duration_sec)}</span>
                    <span>{redacted ? "•••" : a.avg_power_w ? `${a.avg_power_w}W` : a.avg_hr ? `${a.avg_hr}bpm` : "—"}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {modalDate && data[modalDate]?.planned && (
        <PlannedWorkoutModal
          date={modalDate}
          planned={data[modalDate].planned}
          ftpWatts={redacted ? null : ftpWatts}
          onSave={savePlanned}
          onDelete={deletePlanned}
          onClose={() => setModalDate(null)}
        />
      )}

      {coachPlanDate && (
        <CoachPlanModal
          date={coachPlanDate}
          ftpWatts={redacted ? null : ftpWatts}
          onConfirm={confirmCoachPlan}
          onClose={() => setCoachPlanDate(null)}
        />
      )}
    </div>
  );
}
