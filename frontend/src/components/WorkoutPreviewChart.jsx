import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// A stepped %FTP-vs-time profile, the classic Zwift/intervals.icu workout
// shape. Steady steps are flat bars; ramps slope from low to high.
//
// Cadence is optional on a step (overgearing/torque work is defined by low
// cadence at normal power) and most workouts have none at all, so the cadence
// line only appears on its own axis when at least one step actually sets it —
// an all-null cadence workout renders exactly as it did before this feature.
export default function WorkoutPreviewChart({ steps, ftpWatts }) {
  const points = [];
  const cadencePoints = [];
  let t = 0;
  const hasCadence = steps.some((s) => s.cadence_low_rpm != null || s.cadence_high_rpm != null);

  for (const s of steps) {
    const low = s.target_low_pct_ftp * 100;
    const high = (s.target_high_pct_ftp ?? s.target_low_pct_ftp) * 100;
    if (s.target_type === "ramp" || s.target_type === "range") {
      points.push([t, low]);
      points.push([t + s.duration_sec, high]);
    } else {
      points.push([t, low]);
      points.push([t + s.duration_sec, low]);
    }
    if (hasCadence) {
      const cLow = s.cadence_low_rpm ?? s.cadence_high_rpm;
      const cHigh = s.cadence_high_rpm ?? s.cadence_low_rpm;
      cadencePoints.push([t, cLow ?? null]);
      cadencePoints.push([t + s.duration_sec, cHigh ?? null]);
    }
    t += s.duration_sec;
  }

  const totalMin = Math.round(t / 60);

  const option = {
    grid: { left: 50, right: hasCadence ? 50 : 20, top: 20, bottom: 40 },
    xAxis: {
      type: "value",
      max: t,
      axisLabel: { color: colors.muted, formatter: (v) => `${Math.round(v / 60)}m` },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: colors.muted } },
    },
    yAxis: [
      {
        type: "value",
        name: "% FTP",
        nameTextStyle: { color: colors.muted },
        axisLabel: { color: colors.muted },
        splitLine: { lineStyle: { color: colors.grid } },
      },
      ...(hasCadence
        ? [
            {
              type: "value",
              name: "rpm",
              nameTextStyle: { color: colors.warning },
              axisLabel: { color: colors.warning },
              splitLine: { show: false },
            },
          ]
        : []),
    ],
    series: [
      {
        name: "% FTP",
        type: "line",
        data: points,
        step: false,
        lineStyle: { color: colors.blue, width: 2 },
        areaStyle: { color: "rgba(42,120,214,0.2)" },
        symbol: "none",
      },
      ...(hasCadence
        ? [
            {
              name: "Cadence",
              type: "line",
              yAxisIndex: 1,
              data: cadencePoints,
              step: false,
              lineStyle: { color: colors.warning, width: 2, type: "dashed" },
              symbol: "none",
              connectNulls: false,
            },
          ]
        : []),
    ],
    legend: hasCadence ? { data: ["% FTP", "Cadence"], textStyle: { color: colors.muted }, top: 0, right: 0 } : undefined,
    tooltip: {
      trigger: "axis",
      formatter: (p) => {
        const pct = p[0].value[1];
        const w = ftpWatts ? ` (${Math.round((pct / 100) * ftpWatts)}W)` : "";
        const cadenceLine = p[1] && p[1].value[1] != null ? `<br/>${Math.round(p[1].value[1])} rpm` : "";
        return `${Math.round(p[0].value[0] / 60)}min: ${Math.round(pct)}% FTP${w}${cadenceLine}`;
      },
    },
  };

  return (
    <div>
      <ReactECharts option={option} style={{ height: 240, width: "100%" }} notMerge={true} />
      <div className="caption">Total: {totalMin} min</div>
    </div>
  );
}
