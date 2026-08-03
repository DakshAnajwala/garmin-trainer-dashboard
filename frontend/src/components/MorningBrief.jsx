import { useEffect, useState } from "react";
import { api } from "../api";
import { useRedact, redactSensitiveText } from "../redactContext";

const KIND_CLASS = { pr: "brief-pr", weight: "brief-note", delta: "brief-note", none: "brief-muted" };

// The 30-second card: today's session, and the one number that actually
// changed — instead of making you cross-reference five tabs to find out.
// The verdict headline itself renders once, in VerdictBanner right below;
// repeating it here added a line without adding information.
export default function MorningBrief() {
  const { redacted } = useRedact();
  const [data, setData] = useState(null);

  useEffect(() => {
    api.brief().then(setData).catch(() => {});
  }, []);

  if (!data) return null;

  return (
    <div className="morning-brief">
      <div className="morning-brief-session">Today: {data.today_session}</div>
      <div className={`morning-brief-note ${KIND_CLASS[data.brief.kind] ?? "brief-muted"}`}>
        {redactSensitiveText(data.brief.headline, redacted)}
      </div>
      {data.load_advisory?.flagged && (
        <div className={`load-advisory load-advisory-${data.load_advisory.severity}`}>
          ⚠️ {redactSensitiveText(data.load_advisory.message, redacted)}
        </div>
      )}
    </div>
  );
}
