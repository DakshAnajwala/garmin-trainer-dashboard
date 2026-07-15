import { useState } from "react";
import { api } from "../api";

export default function WeightLogger({ latestWeight, onLogged }) {
  const [value, setValue] = useState(latestWeight ?? 70.0);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.logWeight(parseFloat(value));
      onLogged?.();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="weight-logger">
      <label>
        Log today's weight (kg)
        <input
          type="number"
          step="0.1"
          min="25"
          max="200"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <button onClick={save} disabled={saving}>
        {saving ? "Saving..." : "Save weight"}
      </button>
    </div>
  );
}
