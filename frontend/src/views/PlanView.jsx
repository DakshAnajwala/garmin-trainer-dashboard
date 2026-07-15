import { useEffect, useState } from "react";
import { api } from "../api";
import StrengthLog from "../components/StrengthLog";
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

      <h3>Today's session</h3>
      <SessionCard plan={today} isToday={true} redacted={redacted} />

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
