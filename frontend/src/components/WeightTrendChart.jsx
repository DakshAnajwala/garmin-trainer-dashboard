import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// floorKg is the athlete's own guard-rail weight from config/athlete_profile.json
// (a gitignored file), NOT a constant — hardcoding one person's floor here both
// leaked their bodyweight into the repo and silently drew the wrong line for
// anyone else running this. Omitted → no reference line at all.
export default function WeightTrendChart({ history, floorKg = null }) {
  const dates = history.map((h) => h[0]);
  const weights = history.map((h) => h[1]);

  const option = {
    grid: { left: 55, right: 30, top: 30, bottom: 40 },
    xAxis: { type: "category", data: dates, axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.muted } } },
    yAxis: {
      type: "value",
      name: "Weight (kg)",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "line",
        data: weights,
        lineStyle: { color: colors.blue, width: 2 },
        itemStyle: { color: colors.blue },
        symbol: "circle",
        symbolSize: 8,
        markLine: floorKg
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: colors.muted, type: "dotted" },
              label: { formatter: `floor: ${floorKg}kg`, color: colors.muted },
              data: [{ yAxis: floorKg }],
            }
          : undefined,
      },
    ],
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 300, width: "100%" }} notMerge={true} />;
}
