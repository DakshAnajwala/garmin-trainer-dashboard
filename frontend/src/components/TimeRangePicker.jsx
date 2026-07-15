import { useState } from "react";
import DatePicker from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css";
import { toIsoDateLocal } from "../dateUtils";

const DEFAULT_PRESETS = [
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "2M", days: 60 },
  { label: "3M", days: 90 },
];

function isoDaysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toIsoDateLocal(d);
}

// Fires onChange({start, end}) as ISO date strings. Presets are quick buttons
// (customizable via the `presets` prop); "Custom" reveals a 2-month inline
// calendar for exact start/end selection.
export default function TimeRangePicker({ onChange, defaultPreset = "1M", presets = DEFAULT_PRESETS }) {
  const [showCustom, setShowCustom] = useState(false);
  const [customRange, setCustomRange] = useState([null, null]);
  const [selectedPreset, setSelectedPreset] = useState(defaultPreset);

  const applyPreset = (preset) => {
    setSelectedPreset(preset.label);
    setShowCustom(false);
    onChange({ start: isoDaysAgo(preset.days), end: toIsoDateLocal(new Date()) });
  };

  const applyCustom = (dates) => {
    const [start, end] = dates;
    setCustomRange(dates);
    if (start && end) {
      setSelectedPreset(null);
      onChange({ start: toIsoDateLocal(start), end: toIsoDateLocal(end) });
    }
  };

  return (
    <div className="range-picker">
      <div className="range-picker-presets">
        {presets.map((p) => (
          <button
            key={p.label}
            className={selectedPreset === p.label ? "range-btn active" : "range-btn"}
            onClick={() => applyPreset(p)}
          >
            {p.label}
          </button>
        ))}
        <button className={showCustom ? "range-btn active" : "range-btn"} onClick={() => setShowCustom((v) => !v)}>
          Custom {showCustom ? "▲" : "▼"}
        </button>
      </div>
      {showCustom && (
        <div className="range-picker-calendar">
          <DatePicker
            selectsRange
            monthsShown={2}
            inline
            startDate={customRange[0]}
            endDate={customRange[1]}
            onChange={applyCustom}
            maxDate={new Date()}
          />
        </div>
      )}
    </div>
  );
}
