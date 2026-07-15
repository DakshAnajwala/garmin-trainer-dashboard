import { useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { colors } from "../theme";
import { useRedact } from "../redactContext";

function computeStats(samples, startIdx, endIdx) {
  const slice = samples.slice(startIdx, endIdx + 1);
  if (slice.length < 2) return null;
  const first = slice[0];
  const last = slice[slice.length - 1];
  const distance_m = (last.distance_m ?? 0) - (first.distance_m ?? 0);
  const duration_s = (last.elapsed_sec ?? 0) - (first.elapsed_sec ?? 0);

  let elevGain = 0;
  let prevElev = null;
  let firstElev = null;
  for (const s of slice) {
    if (s.elevation_m == null) continue;
    if (firstElev == null) firstElev = s.elevation_m;
    if (prevElev != null) {
      const diff = s.elevation_m - prevElev;
      if (diff > 0) elevGain += diff;
    }
    prevElev = s.elevation_m;
  }

  const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
  const hrVals = slice.map((s) => s.hr_bpm).filter((v) => v != null);
  const powerVals = slice.map((s) => s.power_w).filter((v) => v != null);
  const speedVals = slice.map((s) => s.speed_mps).filter((v) => v != null);

  const netElev = prevElev != null && firstElev != null ? prevElev - firstElev : null;
  const avgGradient = distance_m > 0 && netElev != null ? (netElev / distance_m) * 100 : null;
  const avgSpeed = avg(speedVals);

  return {
    distance_m,
    duration_s,
    elev_gain_m: elevGain,
    avg_gradient_pct: avgGradient,
    avg_hr: avg(hrVals),
    avg_power_w: avg(powerVals),
    avg_speed_kmh: avgSpeed != null ? avgSpeed * 3.6 : null,
  };
}

export default function SegmentAnalyzer({ samples }) {
  const { redacted } = useRedact();
  const [range, setRange] = useState({ startIdx: 0, endIdx: samples.length - 1 });

  const hasElevation = samples.some((s) => s.elevation_m != null);
  const hasPower = samples.some((s) => s.power_w != null);
  const hasDistance = samples.some((s) => s.distance_m != null);

  const xData = samples.map((s) => (hasDistance ? ((s.distance_m ?? 0) / 1000).toFixed(2) : s.elapsed_sec));

  const series = [];
  if (hasElevation) {
    series.push({
      name: "Elevation (m)",
      type: "line",
      data: samples.map((s) => s.elevation_m),
      areaStyle: { color: "rgba(137,135,129,0.25)" },
      lineStyle: { color: colors.muted, width: 1 },
      symbol: "none",
    });
  }
  series.push({
    name: hasPower && !redacted ? "Power (W)" : "Heart rate (bpm)",
    type: "line",
    data: samples.map((s) => (hasPower && !redacted ? s.power_w : s.hr_bpm)),
    lineStyle: { color: colors.blue, width: 1.5 },
    symbol: "none",
  });

  const option = {
    legend: { bottom: 0, textStyle: { color: colors.muted } },
    grid: { left: 50, right: 20, top: 20, bottom: 76 },
    xAxis: {
      type: "category",
      data: xData,
      name: hasDistance ? "Distance (km)" : "Time (s)",
      nameLocation: "middle",
      nameGap: 28,
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      axisLine: { lineStyle: { color: colors.muted } },
    },
    yAxis: { type: "value", axisLabel: { color: colors.muted }, splitLine: { lineStyle: { color: colors.grid } } },
    dataZoom: [
      { type: "inside", start: 0, end: 100 },
      { type: "slider", start: 0, end: 100, height: 22, bottom: 34 },
    ],
    series,
    tooltip: { trigger: "axis" },
  };

  const onEvents = {
    dataZoom: (params) => {
      const info = params.batch ? params.batch[0] : params;
      if (info.start == null || info.end == null) return;
      const startIdx = Math.round((info.start / 100) * (samples.length - 1));
      const endIdx = Math.round((info.end / 100) * (samples.length - 1));
      setRange({ startIdx, endIdx });
    },
  };

  const stats = useMemo(() => computeStats(samples, range.startIdx, range.endIdx), [samples, range]);

  return (
    <div>
      <div className="caption">Drag the slider below the chart to select a segment of this ride.</div>
      <ReactECharts option={option} style={{ height: 320, width: "100%" }} notMerge={true} onEvents={onEvents} />
      {stats && (
        <div className="metric-grid">
          <div className="metric-card">
            <div className="metric-card-label">Distance</div>
            <div className="metric-card-value">{(stats.distance_m / 1000).toFixed(2)} km</div>
          </div>
          <div className="metric-card">
            <div className="metric-card-label">Duration</div>
            <div className="metric-card-value">{Math.round(stats.duration_s / 60)} min</div>
          </div>
          {hasElevation && (
            <div className="metric-card">
              <div className="metric-card-label">Elevation gain</div>
              <div className="metric-card-value">{Math.round(stats.elev_gain_m)} m</div>
            </div>
          )}
          {hasElevation && (
            <div className="metric-card">
              <div className="metric-card-label">Avg gradient</div>
              <div className="metric-card-value">{stats.avg_gradient_pct != null ? `${stats.avg_gradient_pct.toFixed(1)}%` : "—"}</div>
            </div>
          )}
          <div className="metric-card">
            <div className="metric-card-label">Avg speed</div>
            <div className="metric-card-value">{stats.avg_speed_kmh != null ? `${stats.avg_speed_kmh.toFixed(1)} km/h` : "—"}</div>
          </div>
          <div className="metric-card">
            <div className="metric-card-label">Avg HR</div>
            <div className="metric-card-value">{stats.avg_hr != null ? Math.round(stats.avg_hr) : "—"}</div>
          </div>
          {hasPower && (
            <div className="metric-card">
              <div className="metric-card-label">Avg power</div>
              <div className="metric-card-value">{redacted ? "•••" : stats.avg_power_w != null ? `${Math.round(stats.avg_power_w)}W` : "—"}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
