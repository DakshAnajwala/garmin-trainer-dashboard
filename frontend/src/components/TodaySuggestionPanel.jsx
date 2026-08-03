import { useEffect, useState } from "react";
import { api } from "../api";
import WorkoutPreviewChart from "./WorkoutPreviewChart";
import { useRedact, redactSensitiveText } from "../redactContext";

// "What should I do today?" — three options, each individually addable.
//
// The three are not a ranked list of the same answer. Options sharing a `kind`
// are alternatives to each other; the strength option is a different modality
// and stacks with a ride, which is why it advertises that rather than making
// the athlete guess whether picking it cancels the bike session.
//
// Everything here degrades: no weight/FTP logged still returns three usable
// options, and an invalid Anthropic key just means the rationale is the
// deterministic one. Preview-then-confirm, same as every other recommendation
// surface in this app — nothing lands on the calendar without a click.

const KIND_META = {
  bike: { icon: "🚴", badge: "badge-blue" },
  strength: { icon: "🏋️", badge: "badge-good" },
  rest: { icon: "😴", badge: "badge-muted" },
  note: { icon: "📝", badge: "badge-muted" },
};

function OptionCard({ date, option, ftpWatts, redacted, onAdded }) {
  const [busy, setBusy] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [asking, setAsking] = useState(false); // a request is in flight
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState(null);
  const meta = KIND_META[option.kind] ?? KIND_META.note;

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.savePlanned(date, option.workout);
      onAdded?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Seeded with the suggestion itself so the coach answers about THIS session
  // rather than in the abstract. Reuses the existing chat endpoint — a
  // follow-up about a workout is the same coach, just given context.
  const ask = async (text) => {
    if (!text.trim()) return;
    setAsking(true);
    setAnswer(null);
    setError(null);
    const context =
      `The app suggested this session for ${date}: "${option.title}" — ${option.detail} ` +
      `The stated reason was: ${option.reason} ` +
      `My question about it: ${text}`;
    try {
      const r = await api.chat([{ role: "user", content: context }], date);
      setAnswer(r.reply);
    } catch (e) {
      setError(`Couldn't reach the coach: ${e.message}`);
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="suggestion-card">
      <div className="plan-card-top">
        <span className="plan-card-title">
          {meta.icon} {option.title}
        </span>
        <span className={`plan-badge ${meta.badge}`}>
          {option.kind === "strength" ? "pairs with a ride" : option.kind}
        </span>
      </div>

      <div className="plan-card-detail">{redactSensitiveText(option.detail, redacted)}</div>
      {option.duration_min ? <div className="plan-card-meta">~{option.duration_min} min</div> : null}

      <div className="suggestion-reason">💡 {redactSensitiveText(option.reason, redacted)}</div>

      {option.placement_warning && (
        <div className="load-advisory load-advisory-warning">
          ⚠️ {redactSensitiveText(option.placement_warning, redacted)}
        </div>
      )}

      {option.workout?.steps?.length > 0 && (
        <WorkoutPreviewChart steps={option.workout.steps} ftpWatts={ftpWatts} />
      )}

      <div className="modal-actions">
        <button className="primary-btn" onClick={add} disabled={busy}>
          {busy ? "Adding…" : "Add to calendar"}
        </button>
        <button className="followup-btn" onClick={() => setAskOpen((v) => !v)}>
          💬 {askOpen ? "Hide questions" : "Ask about this"}
        </button>
      </div>

      {askOpen && (
        <div className="suggestion-ask">
          <div className="chat-input-row">
            <input
              type="text"
              placeholder="e.g. why this and not intervals? can I do it outdoors?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask(question)}
            />
            <button onClick={() => ask(question)} disabled={asking || !question.trim()}>
              {asking ? "…" : "Ask"}
            </button>
          </div>
          {answer && <div className="chat-content">{answer}</div>}
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

export default function TodaySuggestionPanel({ date, ftpWatts, onAdded }) {
  const { redacted } = useRedact();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .daySuggestions(date, true)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [date]);

  if (loading) return <div className="loading">Working out what today should be…</div>;
  if (error) return <div className="error-box">Couldn't load suggestions: {error}</div>;
  if (!data) return null;

  return (
    <div className="suggestion-panel">
      <div className="caption">
        Three options for {date}. Nothing is scheduled until you add one.
        {data.readiness_verdict && data.readiness_verdict !== "UNKNOWN" && (
          <> Today's readiness reads <strong>{data.readiness_verdict}</strong>.</>
        )}
      </div>

      {/* The signal these are built on. Saying "no weakness signal yet" beats
          silently serving generic advice that looks personalised. */}
      {data.weakest_zone ? (
        !redacted && (
          <div className="caption">
            Targeting your weakest zone: <strong>{data.weakest_zone}</strong>.
          </div>
        )
      ) : (
        <div className="empty-note">
          No weakness signal yet — log a weigh-in and an FTP test and these become targeted at your
          actual limiter rather than general.
        </div>
      )}

      {data.weakest_zone_caveat && !redacted && (
        <div className="junk-notice">
          <span>ℹ️ {data.weakest_zone_caveat}</span>
        </div>
      )}

      {data.traveling && <div className="junk-notice"><span>✈️ You're travelling ({data.traveling}).</span></div>}

      {/* Informational, never a blocker: the deterministic options below are
          all present regardless of whether the AI could run. */}
      {data.ai_unavailable_message && <div className="caption">🤖 {data.ai_unavailable_message}</div>}

      <div className="suggestion-list">
        {data.options.map((o, i) => (
          <OptionCard
            key={`${o.kind}-${i}`}
            date={date}
            option={o}
            ftpWatts={ftpWatts}
            redacted={redacted}
            onAdded={onAdded}
          />
        ))}
      </div>
    </div>
  );
}
