import { useEffect, useState } from "react";
import { api } from "../api";

const TYPES = ["bike", "wheelset", "chain", "cassette", "tires", "other"];

// Activity types a gear item can claim as its default, so rides of that type
// count toward it without per-ride assignment. Matches the Garmin type keys
// the activity list already uses.
const ACTIVITY_TYPES = [
  { key: "road_biking", label: "Outdoor rides" },
  { key: "indoor_cycling", label: "Indoor rides" },
  { key: "virtual_ride", label: "Virtual rides" },
];

export default function GearManager() {
  const [gear, setGear] = useState([]);
  const [devices, setDevices] = useState([]);
  const [form, setForm] = useState({ name: "", type: "bike", install_date: "", accumulated_distance_km: "", notes: "" });

  const refresh = () => api.listGear().then(setGear).catch(() => {});
  useEffect(() => {
    refresh();
    api.activityDevices().then(setDevices).catch(() => {});
  }, []);

  const save = async () => {
    await api.saveGear({
      ...form,
      install_date: form.install_date || null,
      accumulated_distance_km: form.accumulated_distance_km ? Number(form.accumulated_distance_km) : 0,
    });
    setForm({ name: "", type: "bike", install_date: "", accumulated_distance_km: "", notes: "" });
    refresh();
  };

  const del = async (id) => {
    await api.deleteGear(id);
    refresh();
  };

  // Send back the stored fields only — the *_distance_km breakdown the list
  // endpoint computes is derived, not something to write back.
  const toggleDefaultType = async (g, typeKey) => {
    const current = g.default_for_types || [];
    const next = current.includes(typeKey) ? current.filter((t) => t !== typeKey) : [...current, typeKey];
    await api.saveGear({
      id: g.id,
      name: g.name,
      type: g.type,
      install_date: g.install_date || null,
      accumulated_distance_km: g.manual_distance_km ?? 0,
      default_for_types: next,
      default_for_device_ids: g.default_for_device_ids || [],
      notes: g.notes || "",
    });
    refresh();
  };

  const toggleDefaultDevice = async (g, deviceId) => {
    const current = g.default_for_device_ids || [];
    const next = current.includes(deviceId) ? current.filter((d) => d !== deviceId) : [...current, deviceId];
    await api.saveGear({
      id: g.id,
      name: g.name,
      type: g.type,
      install_date: g.install_date || null,
      accumulated_distance_km: g.manual_distance_km ?? 0,
      default_for_types: g.default_for_types || [],
      default_for_device_ids: next,
      notes: g.notes || "",
    });
    refresh();
  };

  return (
    <div className="view-grid">
      <h3>Gear &amp; equipment</h3>
      <div className="caption">
        Total = the starting km you enter here + distance from rides assigned to this gear. Garmin doesn't record which
        bike you rode, so assign gear on an activity in History, or tick an activity type below to claim all rides of
        that type automatically.
      </div>

      <div className="builder-step">
        <input
          className="goal-input-wide"
          placeholder="Name (e.g. Tarmac SL7)"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input type="date" value={form.install_date} onChange={(e) => setForm({ ...form, install_date: e.target.value })} />
        <input
          type="number"
          className="goal-input-wide"
          placeholder="starting km"
          value={form.accumulated_distance_km}
          onChange={(e) => setForm({ ...form, accumulated_distance_km: e.target.value })}
        />
        <button className="primary-btn" onClick={save} disabled={!form.name}>
          Add gear
        </button>
      </div>

      <div className="plan-week">
        {gear.map((g) => (
          <div className="plan-card" key={g.id}>
            <div className="plan-card-top">
              <span className="plan-card-day">{g.type}</span>
              <button className="step-remove" onClick={() => del(g.id)}>
                ✕
              </button>
            </div>
            <div className="plan-card-title">{g.name}</div>
            <div className="gear-total">{g.total_distance_km ?? 0} km</div>
            <div className="plan-card-detail">
              {g.manual_distance_km ?? 0} km starting + {g.auto_distance_km ?? 0} km from {g.auto_activity_count ?? 0}{" "}
              {g.auto_activity_count === 1 ? "ride" : "rides"}
              {g.install_date ? ` — installed ${g.install_date}` : ""}
            </div>
            <div className="gear-defaults">
              <span className="caption">Auto-claim by ride type:</span>
              {ACTIVITY_TYPES.map((t) => (
                <label key={t.key} className="export-category-item">
                  <input
                    type="checkbox"
                    checked={(g.default_for_types || []).includes(t.key)}
                    onChange={() => toggleDefaultType(g, t.key)}
                  />
                  {t.label}
                </label>
              ))}
            </div>
            {devices.length > 0 && (
              <div className="gear-defaults">
                <span className="caption">
                  Auto-claim by recording device (identifies the watch/head unit, not the bike — only useful if your
                  device happens to match your bike):
                </span>
                {devices.map((d) => (
                  <label key={d.device_id} className="export-category-item">
                    <input
                      type="checkbox"
                      checked={(g.default_for_device_ids || []).includes(d.device_id)}
                      onChange={() => toggleDefaultDevice(g, d.device_id)}
                    />
                    Device {d.device_id} ({d.count} rides, e.g. "{d.sample_name}")
                  </label>
                ))}
              </div>
            )}
            {g.notes && <div className="plan-card-meta">{g.notes}</div>}
          </div>
        ))}
        {gear.length === 0 && <div className="empty-note">No gear logged yet.</div>}
      </div>
    </div>
  );
}
