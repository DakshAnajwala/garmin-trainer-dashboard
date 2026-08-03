import { useState } from "react";
import { api } from "../api";
import { useUnits } from "../unitsContext";

const KG_TO_LB = 2.20462;

export default function WeightLogger({ latestWeight, onLogged }) {
  const { imperial } = useUnits();
  const toDisplay = (kg) => (imperial ? +(kg * KG_TO_LB).toFixed(1) : kg);
  const toKg = (v) => (imperial ? v / KG_TO_LB : v);

  const [value, setValue] = useState(toDisplay(latestWeight ?? 70.0));
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.logWeight(toKg(parseFloat(value)));
      onLogged?.();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="weight-logger">
      <label>
        Log today's weight ({imperial ? "lb" : "kg"})
        <input
          type="number"
          step="0.1"
          min={imperial ? 55 : 25}
          max={imperial ? 440 : 200}
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
