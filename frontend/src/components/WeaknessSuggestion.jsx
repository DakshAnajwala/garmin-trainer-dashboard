const SUGGESTIONS = {
  Neuromuscular: {
    title: "Neuromuscular power (5-15s)",
    workout: "6-10x 8-12s max sprints, full recovery (3-5min) between efforts. Quality over quantity — this is about peak force, not fatigue resistance.",
  },
  Anaerobic: {
    title: "Anaerobic capacity (30s-2min)",
    workout: "5-8x 30-60s at max sustainable effort, 3-5min easy recovery. Think 'repeated hard attacks,' not steady-state.",
  },
  VO2max: {
    title: "VO2max (3-8min)",
    workout: "4-6x 3-5min @ 106-120% FTP, equal or slightly shorter recovery. This is already your Wednesday limiter-focus session.",
  },
  "Functional Threshold": {
    title: "Functional Threshold (20-60min)",
    workout: "2-3x 15-20min @ 95-105% FTP, 5-10min recovery between. Or a long steady tempo/sweet-spot block.",
  },
};

function matchSuggestion(weakestZoneLabel) {
  if (!weakestZoneLabel) return null;
  const key = Object.keys(SUGGESTIONS).find((k) => weakestZoneLabel.startsWith(k));
  return key ? SUGGESTIONS[key] : null;
}

export default function WeaknessSuggestion({ weakestZone }) {
  const suggestion = matchSuggestion(weakestZone);
  if (!suggestion) return null;
  return (
    <div className="plan-card">
      <div className="plan-card-title">Suggested focus: {suggestion.title}</div>
      <div className="plan-card-detail">{suggestion.workout}</div>
    </div>
  );
}
