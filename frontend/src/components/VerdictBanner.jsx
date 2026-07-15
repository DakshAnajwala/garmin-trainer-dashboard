import { useRedact, redactSensitiveText } from "../redactContext";

const VERDICT_CLASS = {
  REST: "banner-critical",
  EASY: "banner-warning",
  TRAIN: "banner-good",
  HARD: "banner-good",
  UNKNOWN: "banner-muted",
};

export default function VerdictBanner({ verdict }) {
  const { redacted } = useRedact();
  if (!verdict) return null;
  const cls = VERDICT_CLASS[verdict.verdict] ?? "banner-muted";
  return (
    <div className={`verdict-banner ${cls}`}>
      <div className="verdict-headline">{verdict.headline}</div>
      <div className="verdict-detail">{redactSensitiveText(verdict.detail, redacted)}</div>
    </div>
  );
}
