import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// Three stacked panels sharing one time axis — NOT a multi-axis chart.
// Watts, kilograms and W/kg have unrelated scales, and stacking them on two
// or three y-axes is the classic misleading-chart mistake: the crossings and
// gaps between the lines would be artifacts of axis choice, not real. Small
// multiples give the same "see it all against one timeline" read with none of
// that. See batch_5_combined_assumptions.md.
const PANELS = [
  { key: "ftp_w", name: "FTP", unit: "W", color: colors.blue },
  { key: "weight_kg", name: "Weight", unit: "kg", color: colors.violet },
  { key: "wkg", name: "W/kg", unit: "W/kg", color: colors.good },
];

export default function TrajectoryChart({ trajectory }) {
  const { history = [], forecast = [], target_wkg: targetWkg } = trajectory;
  const dates = [...history.map((h) => h.date), ...forecast.map((f) => f.date)];
  const splitIdx = history.length - 1;

  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const series = [];

  PANELS.forEach((panel, i) => {
    const top = 30 + i * 130;
    grids.push({ left: 60, right: 20, top, height: 90 });
    xAxes.push({
      gridIndex: i,
      type: "category",
      data: dates,
      axisLabel: { show: i === PANELS.length - 1, color: colors.muted },
      axisLine: { lineStyle: { color: colors.muted } },
      axisPointer: { show: true, label: { backgroundColor: colors.blue } },
    });
    yAxes.push({
      gridIndex: i,
      type: "value",
      name: `${panel.name} (${panel.unit})`,
      nameTextStyle: { color: colors.muted, align: "left" },
      scale: true,
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    });

    // Actual and projected are separate series so only the tail is dashed;
    // they overlap at splitIdx to keep the line visually continuous.
    const actual = dates.map((_, j) => (j <= splitIdx ? history[j]?.[panel.key] ?? null : null));
    const projected = dates.map((_, j) => {
      if (j < splitIdx) return null;
      if (j === splitIdx) return history[j]?.[panel.key] ?? null;
      return forecast[j - history.length]?.[panel.key] ?? null;
    });

    series.push({
      name: panel.name,
      type: "line",
      xAxisIndex: i,
      yAxisIndex: i,
      data: actual,
      lineStyle: { color: panel.color, width: 2 },
      itemStyle: { color: panel.color },
      symbolSize: 8,
    });
    if (forecast.length) {
      series.push({
        name: `${panel.name} — projected`,
        type: "line",
        xAxisIndex: i,
        yAxisIndex: i,
        data: projected,
        lineStyle: { color: panel.color, width: 2, type: "dashed", opacity: 0.6 },
        itemStyle: { color: panel.color },
        symbol: "none",
        tooltip: { show: false },
      });
    }

    // The 4.5 W/kg goal only means anything on the W/kg panel.
    if (panel.key === "wkg" && targetWkg) {
      series.push({
        name: "Target",
        type: "line",
        xAxisIndex: i,
        yAxisIndex: i,
        data: dates.map(() => targetWkg),
        lineStyle: { color: colors.critical, width: 1.5, type: "dotted" },
        itemStyle: { color: colors.critical },
        symbol: "none",
        tooltip: { show: false },
      });
    }
  });

  const option = {
    legend: { bottom: 0, textStyle: { color: colors.muted }, data: ["FTP", "Weight", "W/kg", "Target"] },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series,
    axisPointer: { link: [{ xAxisIndex: "all" }] }, // one crosshair across all three panels
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const date = params[0]?.axisValue;
        const row =
          history.find((h) => h.date === date) || forecast.find((f) => f.date === date);
        if (!row) return "";
        const lines = [`<strong>${date}${row.projected ? " (projected)" : ""}</strong>`];
        lines.push(`FTP: ${row.ftp_w}W`);
        lines.push(`Weight: ${row.weight_kg}kg`);
        lines.push(`W/kg: ${row.wkg}`);
        lines.push(`Target at this weight: ${row.target_watts}W`);
        return lines.join("<br/>");
      },
    },
  };

  return <ReactECharts option={option} style={{ height: 460, width: "100%" }} notMerge={true} />;
}
