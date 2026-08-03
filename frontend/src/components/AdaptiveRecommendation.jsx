import { useEffect, useState } from "react";
import { api } from "../api";

// "Plans rewrite themselves ... no coach re-cutting the block" — translated
// as a visible one-click recommendation rather than a silent rewrite: same
// principle as the load advisory and the constraint-driven plan override.
// The trailing week's actual downgrade/load pattern decides whether the
// block controller should advance, hold, or step back — the athlete still
// approves the change.
export default function AdaptiveRecommendation({ onApplied }) {
  const [rec, setRec] = useState(null);
  const [applying, setApplying] = useState(false);

  const load = () => api.adaptiveRecommendation().then(setRec).catch(() => {});

  useEffect(() => {
    load();
  }, []);

  const apply = async () => {
    setApplying(true);
    try {
      await api.setBlockWeek(rec.recommended_block_week);
      await load();
      onApplied?.();
    } finally {
      setApplying(false);
    }
  };

  if (!rec) return null;

  return (
    <div className={`adaptive-rec ${rec.should_change ? "adaptive-rec-actionable" : ""}`}>
      <div className="adaptive-rec-text">{rec.reason}</div>
      {rec.should_change && (
        <button className="primary-btn" onClick={apply} disabled={applying}>
          {applying ? "Applying..." : `Move to block week ${rec.recommended_block_week}`}
        </button>
      )}
    </div>
  );
}
