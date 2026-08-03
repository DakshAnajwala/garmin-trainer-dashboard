import { useEffect, useState } from "react";
import { api } from "../api";
import GearManager from "../components/GearManager";
import AeroProfileForm from "../components/AeroProfileForm";
import CustomAlgoPanel from "../components/CustomAlgoPanel";
import ExportPanel from "../components/ExportPanel";
import { useAuth } from "../authContext";
import { useRedact } from "../redactContext";
import { useUnits } from "../unitsContext";

// Settings is config, not "everything that was scattered".
//
// What moved here: things you set up and then forget (aero position, gear,
// keys, connections). What stayed put: constraints and block week (planning
// inputs you consult and change as life happens — they live with the Plan),
// and the undo log (history, and you want it where the mistake happened).
// The line is consult-vs-configure; without it this tab just becomes the new
// junk drawer, which is the thing we were escaping.
//
// Groups are named for what they're FOR, not which file they come from — you
// look for "my keys", not "secrets.enc.json".

function Section({ title, caption, children }) {
  return (
    <div className="settings-section">
      <h3>{title}</h3>
      {caption && <div className="caption">{caption}</div>}
      {children}
    </div>
  );
}

function SecretRow({ secret, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      await api.setSecret(secret.name, value);
      setValue(""); // never keep the value around after it's stored
      setEditing(false);
    });

  const revoke = () => {
    if (!window.confirm(`Revoke ${secret.label}?\n\n${secret.breaks}`)) return;
    run(() => api.revokeSecret(secret.name));
  };

  return (
    <div className="settings-row data-field">
      <div className="settings-row-main">
        <div className="settings-row-title">
          {secret.label}
          <span className={`plan-badge ${secret.configured ? "badge-good" : "badge-muted"}`}>
            {secret.configured ? "configured" : "not set"}
          </span>
        </div>
        <div className="caption">{secret.powers}</div>
        {!secret.settable && <div className="caption">{secret.help}</div>}
      </div>

      <div className="settings-row-actions">
        {secret.settable &&
          (editing ? (
            <>
              {/* type=password: the value is never rendered back, and this stops
                  it landing in a screenshot or a shoulder-surf. */}
              <input
                type="password"
                autoComplete="off"
                placeholder={secret.help}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                style={{ minWidth: 220 }}
              />
              <button className="followup-btn" onClick={save} disabled={busy || !value.trim()}>
                Save
              </button>
              <button className="followup-btn" onClick={() => { setEditing(false); setValue(""); }}>
                Cancel
              </button>
            </>
          ) : (
            <button className="followup-btn" onClick={() => setEditing(true)} disabled={busy}>
              {secret.configured ? "Replace" : "Set key"}
            </button>
          ))}
        {secret.configured && (
          <button className="followup-btn danger-btn" onClick={revoke} disabled={busy}>
            Revoke
          </button>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

export default function SettingsView() {
  const { redacted, toggle: toggleRedact } = useRedact();
  const { imperial, toggle: toggleUnits } = useUnits();
  const { user, signOut } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [athleteId, setAthleteId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () =>
    api
      .settings()
      .then((d) => {
        setData(d);
        setAthleteId(d.intervals.athlete_id || "");
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="error-box">Couldn't reach the backend: {error}</div>;
  if (!data) return <div className="loading">Loading settings...</div>;

  const saveIntervals = async () => {
    setBusy(true);
    try {
      await api.setIntervalsAthlete(athleteId);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const resync = async () => {
    setBusy(true);
    try {
      const r = await api.resyncToCloud();
      window.alert(`Pushed to Firestore: ${r.keys_pushed.join(", ")}`);
    } catch (e) {
      window.alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-grid">
      {/* Physiology used to live here as a "You" section. It moved to the
          Athlete tab: it's identity, not configuration — it was only ever here
          because this is where config went. */}
      <Section
        title="Connections"
        caption="Keys are encrypted at rest and never displayed — only whether they're set. Revoking only ever removes capability."
      >
        {data.secrets.map((s) => (
          <SecretRow key={s.name} secret={s} onChanged={load} />
        ))}

        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">
              intervals.icu athlete ID
              <span className={`plan-badge ${data.intervals.configured ? "badge-good" : "badge-muted"}`}>
                {data.intervals.configured ? "connected" : "not connected"}
              </span>
            </div>
            <div className="caption">
              The numeric ID from your intervals.icu profile URL. Not a secret — it's a public account number.
              {data.intervals.athlete_id_source === "env" && " Currently coming from .env."}
            </div>
          </div>
          <div className="settings-row-actions">
            <input
              type="text"
              placeholder="e.g. 123456"
              value={athleteId}
              onChange={(e) => setAthleteId(e.target.value)}
              style={{ minWidth: 140 }}
            />
            <button className="followup-btn" onClick={saveIntervals} disabled={busy}>
              Save
            </button>
          </div>
        </div>

        <div className="caption">
          <strong>Deliberately not editable here:</strong>{" "}
          {data.excluded_config.map((e) => `${e.name} — ${e.reason}`).join(" ")}
        </div>
      </Section>

      <Section title="Equipment" caption="Set once, rarely touched — which is why it lives here rather than in a tab.">
        <h3>Bikes &amp; gear</h3>
        <GearManager />
        <h3>Aero setup</h3>
        <AeroProfileForm />
      </Section>

      <Section title="Display">
        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">Units</div>
            <div className="caption">Display only — everything is stored in metric.</div>
          </div>
          <div className="settings-row-actions">
            <button className="followup-btn" onClick={toggleUnits}>
              {imperial ? "🇺🇸 lb / mi" : "🌍 kg / km"}
            </button>
          </div>
        </div>
        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">Redacted Mode</div>
            <div className="caption">Hides fitness numbers so you can share your screen.</div>
          </div>
          <div className="settings-row-actions">
            <button className="followup-btn" onClick={toggleRedact}>
              {redacted ? "🙈 Redacted" : "👁️ Showing fitness data"}
            </button>
          </div>
        </div>
      </Section>

      <Section title="Your model" caption="Bring your own algorithm, or take your model elsewhere.">
        <CustomAlgoPanel onModelChanged={() => {}} />
        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">Export model</div>
            <div className="caption">Your CP, W′, durability and overrides as portable JSON — not just raw data.</div>
          </div>
          <div className="settings-row-actions">
            <button className="followup-btn" onClick={() => api.exportModel().catch(() => {})}>
              Export
            </button>
          </div>
        </div>
      </Section>

      <Section title="Data & backups">
        <ExportPanel />

        <h3>Backups</h3>
        <div className="caption">
          Taken automatically before every write, kept in <code>~/.garmin-trainer-dashboard/backups/</code>. Restore
          with <code>python -m scripts.backups</code> — deliberately a CLI step, since a restore overwrites live data.
        </div>
        {data.backups.length ? (
          <div className="exclusion-ranges">
            {data.backups.map((b) => (
              <span className="exclusion-range" key={b.path}>
                {b.date} · {(b.size_bytes / 1024).toFixed(0)} KB
              </span>
            ))}
          </div>
        ) : (
          <div className="empty-note">No backups yet.</div>
        )}

        <h3>Cloud sync</h3>
        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">
              Firestore
              <span className={`plan-badge ${data.sync.firestore_available ? "badge-good" : "badge-muted"}`}>
                {data.sync.firestore_available ? "connected" : "local only"}
              </span>
            </div>
            <div className="caption">{data.sync.note}</div>
          </div>
          <div className="settings-row-actions">
            <button
              className="followup-btn"
              onClick={resync}
              disabled={busy || !data.sync.firestore_available}
              title="Push local data up, overwriting the cloud copy. Needed after restoring a backup."
            >
              Push local → cloud
            </button>
          </div>
        </div>
        <div className="caption">Synced: {data.sync.synced_keys.join(", ")}</div>
      </Section>

      <Section title="Account">
        <div className="settings-row data-field">
          <div className="settings-row-main">
            <div className="settings-row-title">Signed in</div>
            <div className="caption">
              {user?.email || "—"} · Signing out also wipes this device's cached copy of your data.
            </div>
          </div>
          <div className="settings-row-actions">
            <button className="followup-btn" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </Section>
    </div>
  );
}
