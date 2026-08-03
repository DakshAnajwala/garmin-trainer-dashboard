import { useEffect, useState } from "react";
import { api } from "../api";

// Framework only, per athlete request: capture bike-setup parameters now;
// the actual CdA/power-required-for-speed calculator (the original "wind
// tunnel" idea) and a designated frameset/wheelset library are follow-ups.
export default function AeroProfileForm() {
  const [profile, setProfile] = useState(null);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    api.getAeroProfile().then(setProfile).catch(() => setProfile({ position: "relaxed", frame_type: "neutral" }));
  }, []);

  if (!profile) return <div className="loading">Loading...</div>;

  const update = (patch) => setProfile((p) => ({ ...p, ...patch }));

  const save = async () => {
    await api.saveAeroProfile(profile);
    setStatus("Saved.");
  };

  return (
    <div className="view-grid">
      <h3>Bike & position setup</h3>
      <div className="caption">
        Framework only for now — captures your setup so a real aero/power-required calculator (CdA vs. speed) can be
        built on top of this later, along with a library of specific framesets/wheelsets.
      </div>

      <div className="aero-form">
        <label>
          Height (cm)
          <input type="number" value={profile.height_cm ?? ""} onChange={(e) => update({ height_cm: Number(e.target.value) })} />
        </label>
        <label>
          Weight (kg)
          <input type="number" step="0.1" value={profile.weight_kg ?? ""} onChange={(e) => update({ weight_kg: Number(e.target.value) })} />
        </label>
        <label>
          Riding position
          <select value={profile.position} onChange={(e) => update({ position: e.target.value })}>
            <option value="relaxed">Relaxed (tops/hoods)</option>
            <option value="aero">Aero (drops)</option>
            <option value="tt">TT (aero bars)</option>
          </select>
        </label>
        <label>
          Frame type
          <select value={profile.frame_type} onChange={(e) => update({ frame_type: e.target.value })}>
            <option value="aero">Aero</option>
            <option value="neutral">Neutral / all-rounder</option>
            <option value="endurance">Endurance</option>
            <option value="tt">TT / Triathlon</option>
          </select>
        </label>
        <label>
          Wheelset depth (mm)
          <input
            type="number"
            value={profile.wheelset_depth_mm ?? ""}
            onChange={(e) => update({ wheelset_depth_mm: Number(e.target.value) })}
          />
        </label>
        <button className="primary-btn" onClick={save}>
          Save
        </button>
        {status && <span className="caption">{status}</span>}
      </div>
    </div>
  );
}
