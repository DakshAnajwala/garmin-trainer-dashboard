import { useEffect, useState } from "react";
import { api } from "../api";
import RiderProfileCard from "../components/RiderProfileCard";
import { PARAM_LABEL, AdvisoryBanner } from "../components/modelShared";
import { useRedact } from "../redactContext";

// One question, two halves: what you *declared* about yourself, and what the
// app *worked out* from your rides. They used to live in two places — declared
// physiology buried in Settings (because that's where config went), measured
// parameters in a "Model" tab — which split the same subject across the app.
//
// The declared half stays read-only on purpose. Those numbers aren't
// preferences: ftp_test_factor moves the CP fit, max_hr_bpm moves every zone,
// floor_weight_kg is a safety rail. Making them editable needs the same
// lock/reason/provenance machinery the measured half already has, and that's
// its own pass — not a rider on a navigation change. So instead of a form,
// each one explains what it drives, which is the thing nothing else says.

const CONF_BADGE = { low: "badge-warning", medium: "badge-blue", high: "badge-good", user: "badge-good" };

function DeclaredField({ field }) {
  return (
    <div className="metric-card data-field model-param">
      <div className="calendar-nav">
        <div className="metric-card-label">{field.label}</div>
        <span className="plan-badge badge-muted">declared</span>
      </div>
      <div className="metric-card-value" style={{ fontSize: Array.isArray(field.value) || String(field.value).length > 12 ? 15 : 24 }}>
        {Array.isArray(field.value) ? field.value.join("–") : field.value}
        {field.unit && <span className="caption"> {field.unit}</span>}
      </div>
      <div className="caption">Source: {field.source}</div>
      <div className="model-reasoning">
        <strong>Drives:</strong> {field.drives}
      </div>
    </div>
  );
}

function MeasuredParam({ name, param, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(param.value ?? "");
  const [reason, setReason] = useState("");
  const [advisory, setAdvisory] = useState(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const res = await api.setModelOverride({ name, value: parseFloat(value), locked: true, reason });
      setAdvisory(res.advisory);
      setEditing(false);
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  const unlock = async () => {
    setBusy(true);
    try {
      await api.setModelOverride({ name, value: null, locked: false });
      setAdvisory(null);
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="metric-card data-field model-param">
      <div className="calendar-nav">
        <div className="metric-card-label">{PARAM_LABEL[name] || name}</div>
        <span className={`plan-badge ${CONF_BADGE[param.confidence] || "badge-muted"}`}>
          {param.confidence === "user" ? "yours" : `${param.confidence} confidence`}
        </span>
      </div>
      <div className="metric-card-value">
        {param.value}
        <span className="caption"> {param.unit}</span>
        {param.locked && " 🔒"}
      </div>
      <div className="caption">Source: {param.source}</div>
      <div className="model-reasoning">{param.reasoning}</div>
      {param.locked && param.computed_value != null && (
        <div className="caption">Auto-computed value (held back by your lock): {param.computed_value}</div>
      )}

      {editing ? (
        <div className="model-override-form">
          <input type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} />
          <input
            type="text"
            placeholder="Why? (e.g. post-illness — logged with the override)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div style={{ display: "flex", gap: 6 }}>
            <button className="followup-btn" onClick={save} disabled={busy || value === ""}>
              Set &amp; lock
            </button>
            <button className="followup-btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 6 }}>
          <button className="followup-btn" onClick={() => setEditing(true)}>
            Override
          </button>
          {param.locked && (
            <button className="followup-btn" onClick={unlock} disabled={busy}>
              Unlock (return to auto)
            </button>
          )}
        </div>
      )}
      <AdvisoryBanner advisory={advisory} />
    </div>
  );
}

export default function AthleteView() {
  const { redacted } = useRedact();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = () =>
    api
      .athlete()
      .then(setData)
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const recompute = async () => {
    await api.model(true);
    load();
  };

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!data) return <div className="loading">Loading your athlete profile...</div>;
  if (redacted) {
    return <div className="empty-note">Your physiology is hidden in Redacted Mode.</div>;
  }

  const { declared, model, phenotype } = data;

  return (
    <div className="view-grid">
      {declared.using_example_profile && (
        <div className="junk-notice">
          <span>
            <strong>You're on the example profile.</strong> Every W/kg, zone and coaching answer is a
            placeholder until you copy <code>config/athlete_profile.example.json</code> to{" "}
            <code>{declared.source_file}</code> and put your own numbers in.
          </span>
        </div>
      )}

      {phenotype?.type && (
        <>
          <h3>Rider type</h3>
          <RiderProfileCard profile={phenotype} />
        </>
      )}

      <h3>What you declared</h3>
      <div className="caption">{declared.why_read_only}</div>
      <div className="metric-grid">
        {declared.fields.map((f) => (
          <DeclaredField key={f.key} field={f} />
        ))}
      </div>

      <div className="calendar-nav">
        <h3 style={{ margin: 0 }}>What your rides say</h3>
        <button className="followup-btn" onClick={recompute}>
          Recompute from data
        </button>
      </div>
      <div className="caption">
        Every number here is inspectable: value, source, confidence, and the reasoning behind it. Lock any
        parameter to stop auto-recompute overwriting what you know (illness, a new meter) — computed from{" "}
        {model.inputs_snapshot?.rides_analyzed?.length ?? 0} cached ride(s).
      </div>
      <div className="metric-grid">
        {Object.entries(model.params).map(([name, p]) => (
          <MeasuredParam key={name} name={name} param={p} onSaved={load} />
        ))}
      </div>

      <div className="caption">
        Bringing your own algorithm, or exporting this model, lives in Settings → Your model.
      </div>
    </div>
  );
}
