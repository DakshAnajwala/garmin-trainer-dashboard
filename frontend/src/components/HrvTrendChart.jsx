import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function HrvTrendChart({ records }) {
  const filtered = records.filter((r) => r.last_night_avg_ms != null);
  const dates = filtered.map((r) => r.date);
  const values = filtered.map((r) => r.last_night_avg_ms);
  const weeklyAvg = filtered.map((r) => r.weekly_avg_ms);
  const baselineLow = filtered.map((r) => r.baseline_low_ms);
  const bandWidth = filtered.map((r) =>
    r.baseline_high_ms != null && r.baseline_low_ms != null ? r.baseline_high_ms - r.baseline_low_ms : null
  );
  const hasBand = baselineLow.every((v) => v != null) && bandWidth.every((v) => v != null);

  const series = [];
  if (hasBand) {
    series.push({
      name: "baseline-floor",
      type: "line",
      data: baselineLow,
      stack: "band",
      lineStyle: { opacity: 0 },
      areaStyle: { opacity: 0 },
      symbol: "none",
      silent: true,
      tooltip: { show: false },
    });
    series.push({
      name: "Balanced baseline band",
      type: "line",
      data: bandWidth,
      stack: "band",
      lineStyle: { opacity: 0 },
      areaStyle: { color: "rgba(134,182,239,0.25)" },
      itemStyle: { color: "rgba(134,182,239,0.6)" },
      symbol: "none",
      silent: true,
    });
  }
  series.push({
    name: "7-day avg",
    type: "line",
    data: weeklyAvg,
    lineStyle: { color: colors.blueDark, width: 2, type: "dashed" },
    itemStyle: { color: colors.blueDark },
    symbol: "none",
  });
  series.push({
    name: "Last night HRV",
    type: "line",
    data: values,
    lineStyle: { color: colors.blue, width: 2 },
    itemStyle: { color: colors.blue },
    symbolSize: 6,
  });

  const option = {
    grid: { left: 55, right: 30, top: 30, bottom: 60 },
    legend: {
      bottom: 0,
      textStyle: { color: colors.muted },
      data: ["Balanced baseline band", "7-day avg", "Last night HRV"],
    },
    xAxis: { type: "category", data: dates, axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.muted } } },
    yAxis: {
      type: "value",
      name: "HRV (ms)",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series,
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 360, width: "100%" }} notMerge={true} />;
}
