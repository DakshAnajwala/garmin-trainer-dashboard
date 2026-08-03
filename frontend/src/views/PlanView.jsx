import { useEffect, useState } from "react";
import { api } from "../api";
import AdaptiveRecommendation from "../components/AdaptiveRecommendation";
import ConstraintsPanel from "../components/ConstraintsPanel";
import ReflowPanel from "../components/ReflowPanel";
import StrengthLog from "../components/StrengthLog";
import WeeklyDistanceCompliance from "../components/WeeklyDistanceCompliance";
import { useRedact, redactSensitiveText } from "../redactContext";

const SESSION_BADGE = {
  rest: "badge-muted",
  endurance: "badge-blue",
  intervals: "badge-critical",
  team_ride: "badge-good",
  long_ride: "badge-blue",
  endurance_swap: "badge-warning",
  rest_swap: "badge-warning",
};

function SessionCard({ plan, isToday, redacted }) {
  const advisory = plan.load_advisory;
  return (
    <div className={`plan-card ${isToday ? "plan-card-active" : ""}`}>
      <div className="plan-card-top">
        <span className="plan-card-day">{plan.day_name}</span>
        <span className={`plan-badge ${SESSION_BADGE[plan.session_type] ?? "badge-muted"}`}>
          {plan.session_type.replace("_", " ")}
        </span>
      </div>
      <div className="plan-card-title">{plan.title}</div>
      <div className="plan-card-detail">{redactSensitiveText(plan.detail, redacted)}</div>
      {plan.duration_min && <div className="plan-card-meta">~{plan.duration_min} min</div>}
      {advisory?.flagged && (
        <div className={`load-advisory load-advisory-${advisory.severity}`}>
          ⚠️ {redactSensitiveText(advisory.message, redacted)}
        </div>
      )}
    </div>
  );
}

export default function PlanView() {
  const { redacted } = useRedact();
  const [weekPlan, setWeekPlan] = useState(null);
  const [today, setToday] = useState(null);
  const [blockWeek, setBlockWeekState] = useState(1);
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    try {
      const bw = await api.getBlockWeek();
      setBlockWeekState(bw.block_week);
      const [week, todayP] = await Promise.all([api.weekPlan(), api.todayPlan()]);
      setWeekPlan(week);
      setToday(todayP);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const changeBlockWeek = async (w) => {
    await api.setBlockWeek(w);
    load();
  };

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!weekPlan || !today) return <div className="loading">Building your plan...</div>;

  return (
    <div className="view-grid">
      {/* This page computes a template week on the fly; it schedules nothing.
          Without saying so, a full week of prescribed sessions reads as "the
          app has planned my week", which is exactly the impression the
          calendar's opt-in generate flow exists to avoid. */}
      <div className="caption">
        A projection of what your week would look like, recomputed live — nothing here is scheduled.
        Use <strong>Calendar → Add calendar entry</strong> to actually put a session on a day.
      </div>

      <WeeklyDistanceCompliance />

      <div className="plan-header">
        <label>
          Block week (1&ndash;4, week 4 = recovery):{" "}
          <select value={blockWeek} onChange={(e) => changeBlockWeek(Number(e.target.value))}>
            {[1, 2, 3, 4].map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </label>
      </div>

      <AdaptiveRecommendation onApplied={load} />

      <ConstraintsPanel onChanged={load} />

      <ReflowPanel />

      <h3>Today's session</h3>
      {today.rationale && <div className="caption">Why: {redactSensitiveText(today.rationale, redacted)}</div>}
      <SessionCard plan={today} isToday={true} redacted={redacted} />
      <div className="calendar-nav">
        {today.decision ? (
          <span className="caption">
            You {today.decision.decision} today&apos;s session{today.decision.reason ? ` — "${today.decision.reason}"` : ""}.
          </span>
        ) : (
          <>
            <button className="followup-btn" onClick={async () => { await api.todayDecision({ decision: "accepted" }); load(); }}>
              ✓ Accept
            </button>
            <button
              className="followup-btn"
              onClick={async () => {
                const reason = window.prompt("Doing something different — what and why? (logged, not judged)");
                if (!reason) return;
                await api.todayDecision({ decision: "overridden", reason });
                load();
              }}
            >
              Override &amp; log why
            </button>
          </>
        )}
      </div>

      <h3>This week</h3>
      <div className="plan-week">
        {weekPlan.map((p) => (
          <SessionCard key={p.weekday} plan={p} isToday={p.weekday === today.weekday} redacted={redacted} />
        ))}
      </div>

      <h3>Strength training</h3>
      <StrengthLog />
    </div>
  );
}
