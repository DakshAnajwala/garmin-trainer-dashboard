import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import { api } from "../api";
import { colors } from "../theme";

// Excluding power is a judgement about *data quality*, so it lives next to the
// ride's power graph rather than in settings — you decide by looking at the
// trace. Nothing here edits the ride: exclusion only filters what the power
// curve and FTP aggregate over, and it's reversible at any time.

function fmtClock(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function PowerExclusionPanel({ activityId, samples }) {
  const [state, setState] = useState(null);
  const [reason, setReason] = useState("");
  const [dismissed, setDismissed] = useState([]);
  const [saving, setSaving] = useState(false);
  const [brush, setBrush] = useState(null);
  const reasonTouched = useRef(false);

  const load = useCallback(async () => {
    const data = await api.powerExclusion(activityId);
    setState(data);
    // Don't clobber what the user is typing if this resolves late — the same
    // race that silently ate ride debriefs before it was guarded.
    if (!reasonTouched.current) setReason(data.reason || "");
  }, [activityId]);

  useEffect(() => {
    reasonTouched.current = false;
    setBrush(null);
    setDismissed([]);
    load().catch(() => setState(null));
  }, [activityId, load]);

  const powered = useMemo(() => samples.filter((s) => s.power_w != null), [samples]);

  const save = async (patch) => {
    setSaving(true);
    try {
      const next = await api.setPowerExclusion(activityId, patch);
      setState((prev) => ({ ...prev, ...next }));
    } finally {
      setSaving(false);
    }
  };

  if (!powered.length) return null;
  if (!state) return <div className="loading">Loading power data quality...</div>;

  const ranges = state.ranges || [];
  const suggestions = (state.suggestions || []).filter((s) => !dismissed.includes(s.code));

  const addRange = async () => {
    if (!brush) return;
    await save({ ranges: [...ranges, brush] });
    setBrush(null);
  };

  const removeRange = (i) => save({ ranges: ranges.filter((_, idx) => idx !== i) });

  const xData = powered.map((s) => s.elapsed_sec);
  const chartOption = {
    grid: { left: 48, right: 16, top: 24, bottom: 44 },
    xAxis: {
      type: "category",
      data: xData,
      axisLabel: { formatter: (v) => fmtClock(Number(v)), color: colors.muted },
    },
    yAxis: { type: "value", name: "W", axisLabel: { color: colors.muted } },
    tooltip: {
      trigger: "axis",
      formatter: (p) => `${fmtClock(Number(p[0].axisValue))} — ${Math.round(p[0].data)}W`,
    },
    dataZoom: [{ type: "slider", height: 18, bottom: 8, labelFormatter: () => "" }],
    series: [
      {
        type: "line",
        data: powered.map((s) => s.power_w),
        showSymbol: false,
        lineStyle: { width: 1, color: colors.blue },
        // Shade the stretches already excluded so the graph shows the state,
        // not just the list below it.
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(220, 80, 80, 0.18)" },
          data: ranges.map((r) => [{ xAxis: String(r.start_sec) }, { xAxis: String(r.end_sec) }]),
        },
      },
    ],
    brush: { toolbox: ["lineX", "clear"], xAxisIndex: 0, throttleType: "debounce" },
    toolbox: { show: false },
  };

  const onBrush = (params) => {
    const area = params.areas?.[0];
    if (!area?.coordRange) return setBrush(null);
    const [a, b] = area.coordRange;
    const start = xData[Math.max(0, Math.round(a))];
    const end = xData[Math.min(xData.length - 1, Math.round(b))];
    if (start != null && end != null && end > start) setBrush({ start_sec: start, end_sec: end });
  };

  return (
    <div className="exclusion-panel">
      <div className="calendar-nav">
        <h3>Power data quality</h3>
        {state.excluded && <span className="plan-badge badge-warning">excluded from curves</span>}
      </div>

      {suggestions.map((s) => (
        <div className="junk-notice" key={s.code}>
          <span>
            <strong>Possible calibration issue.</strong> {s.detail}
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className="followup-btn"
              onClick={() =>
                save({
                  excluded: true,
                  reason: reason || s.code.replace(/_/g, " "),
                }).then(() => setDismissed((d) => [...d, s.code]))
              }
            >
              Exclude this ride's power
            </button>
            {!!s.suggested_ranges?.length && (
              <button
                className="followup-btn"
                onClick={() =>
                  save({ ranges: [...ranges, ...s.suggested_ranges] }).then(() =>
                    setDismissed((d) => [...d, s.code])
                  )
                }
              >
                Exclude just the flagged {s.suggested_ranges.length === 1 ? "moment" : "moments"}
              </button>
            )}
            <button className="followup-btn" onClick={() => setDismissed((d) => [...d, s.code])}>
              Dismiss
            </button>
          </div>
        </div>
      ))}

      <label className="exclusion-toggle">
        <input
          type="checkbox"
          checked={!!state.excluded}
          disabled={saving}
          onChange={(e) => save({ excluded: e.target.checked, reason })}
        />
        <span>
          Exclude this ride's power from the power curve &amp; FTP
          <span className="caption">
            {" "}
            — distance, duration, HR and ride history are unaffected, and the raw data is kept, so you
            can undo this at any time.
          </span>
        </span>
      </label>

      <input
        className="exclusion-reason"
        type="text"
        placeholder="Reason (optional) — e.g. forgot to zero the offset"
        value={reason}
        onChange={(e) => {
          reasonTouched.current = true;
          setReason(e.target.value);
        }}
        onBlur={() => save({ reason })}
      />

      <div className="caption">
        Calibration can drift mid-ride — drag across the graph to exclude just the bad stretch.
      </div>
      <ReactECharts
        option={chartOption}
        style={{ height: 220 }}
        onEvents={{ brushSelected: onBrush }}
        notMerge
      />

      {brush && (
        <div className="junk-notice">
          <span>
            Selected {fmtClock(brush.start_sec)}–{fmtClock(brush.end_sec)}
          </span>
          <button className="followup-btn" onClick={addRange} disabled={saving}>
            Exclude this segment
          </button>
        </div>
      )}

      {!!ranges.length && (
        <div className="exclusion-ranges">
          {ranges.map((r, i) => (
            <span className="exclusion-range" key={`${r.start_sec}-${r.end_sec}-${i}`}>
              {fmtClock(r.start_sec)}–{fmtClock(r.end_sec)}
              <button onClick={() => removeRange(i)} title="Re-include this segment">
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
