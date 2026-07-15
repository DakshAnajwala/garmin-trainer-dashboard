import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function WeightTrendChart({ history }) {
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
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: colors.muted, type: "dotted" },
          label: { formatter: "floor: 57kg", color: colors.muted },
          data: [{ yAxis: 57 }],
        },
      },
    ],
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 300, width: "100%" }} notMerge={true} />;
}
