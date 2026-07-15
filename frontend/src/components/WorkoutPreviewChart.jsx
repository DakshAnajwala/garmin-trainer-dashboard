import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// A stepped %FTP-vs-time profile, the classic Zwift/intervals.icu workout
// shape. Steady steps are flat bars; ramps slope from low to high.
export default function WorkoutPreviewChart({ steps, ftpWatts }) {
  const points = [];
  let t = 0;
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
    t += s.duration_sec;
  }

  const totalMin = Math.round(t / 60);

  const option = {
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "value",
      max: t,
      axisLabel: { color: colors.muted, formatter: (v) => `${Math.round(v / 60)}m` },
      splitLine: { show: false },
      axisLine: { lineStyle: { color: colors.muted } },
    },
    yAxis: {
      type: "value",
      name: "% FTP",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "line",
        data: points,
        step: false,
        lineStyle: { color: colors.blue, width: 2 },
        areaStyle: { color: "rgba(42,120,214,0.2)" },
        symbol: "none",
      },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (p) => {
        const pct = p[0].value[1];
        const w = ftpWatts ? ` (${Math.round((pct / 100) * ftpWatts)}W)` : "";
        return `${Math.round(p[0].value[0] / 60)}min: ${Math.round(pct)}% FTP${w}`;
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
