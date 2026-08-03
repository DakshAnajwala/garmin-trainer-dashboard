import { useEffect, useState } from "react";
import { api } from "../api";
import { PARAM_LABEL, AdvisoryBanner } from "./modelShared";

// Extracted from ModelView: pointing the app at your own compute endpoint
// is a connection + credential, which is Settings — not a model view.
// The model inspector still owns *reading* the params; this owns the key.

function CustomAlgoPanel({ onModelChanged }) {
  const [status, setStatus] = useState(null);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [proposal, setProposal] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.customAlgoStatus().then(setStatus).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) return null;

  return (
    <div className="exclusion-panel">
      <h3>Bring your own algorithm</h3>
      <div className="caption">
        Point the app at your own model endpoint (your LLM, your notebook, your code). Your key is encrypted at
        rest, never logged, and revocable here. Returned parameters are validated, clamped to physiological
        bounds, and diffed — nothing applies until you say so.
      </div>

      {status.configured ? (
        <div className="calendar-nav">
          <span className="caption">Endpoint: {status.endpoint_url} (key stored, encrypted)</span>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="followup-btn" onClick={() => run(async () => setProposal(await api.customAlgoPropose()))} disabled={busy}>
              {busy ? "Running..." : "Run & preview"}
            </button>
            <button className="followup-btn danger-btn" onClick={() => run(async () => { await api.customAlgoRevoke(); setProposal(null); refresh(); })}>
              Revoke key
            </button>
          </div>
        </div>
      ) : (
        <div className="model-override-form">
          <input type="url" placeholder="https://your-endpoint.example.com/model" value={url} onChange={(e) => setUrl(e.target.value)} />
          <input type="password" placeholder="Your API key (encrypted at rest, never logged)" value={key} onChange={(e) => setKey(e.target.value)} />
          <button
            className="followup-btn"
            disabled={busy || !url || !key}
            onClick={() => run(async () => { await api.customAlgoConfigure({ endpoint_url: url, api_key: key }); setKey(""); refresh(); })}
          >
            Save endpoint
          </button>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      {proposal && (
        <div className="view-grid">
          <h3>Your algorithm proposes:</h3>
          {Object.entries(proposal.diff).length === 0 && <div className="caption">No changes vs the current model.</div>}
          {Object.entries(proposal.diff).map(([name, d]) => (
            <div className="caption" key={name}>
              <strong>{PARAM_LABEL[name] || name}</strong>: {d.current} → {d.proposed}
            </div>
          ))}
          {proposal.validation_notes.length > 0 && (
            <div className="caption">Validation: {proposal.validation_notes.join(" ")}</div>
          )}
          <AdvisoryBanner advisory={proposal.advisory} />
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className="followup-btn"
              disabled={busy}
              onClick={() => run(async () => { await api.customAlgoApply(proposal.proposed); setProposal(null); onModelChanged(); })}
            >
              Apply (locks these params)
            </button>
            <button className="followup-btn" onClick={() => setProposal(null)}>
              Discard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default CustomAlgoPanel;
