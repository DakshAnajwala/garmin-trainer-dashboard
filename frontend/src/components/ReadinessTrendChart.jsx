import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function ReadinessTrendChart({ records }) {
  const filtered = records.filter((r) => r.readiness_score != null);
  const dates = filtered.map((r) => r.date);
  const scores = filtered.map((r) => r.readiness_score);

  const option = {
    grid: { left: 55, right: 30, top: 30, bottom: 40 },
    xAxis: { type: "category", data: dates, axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.muted } } },
    yAxis: {
      type: "value",
      name: "Readiness score",
      min: 0,
      max: 100,
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "line",
        data: scores,
        lineStyle: { color: colors.blue, width: 2 },
        itemStyle: { color: colors.blue },
        symbolSize: 6,
        markArea: {
          silent: true,
          data: [
            [{ yAxis: 0, itemStyle: { color: colors.critical, opacity: 0.08 } }, { yAxis: 25 }],
            [{ yAxis: 25, itemStyle: { color: colors.warning, opacity: 0.08 } }, { yAxis: 50 }],
            [{ yAxis: 75, itemStyle: { color: colors.good, opacity: 0.08 } }, { yAxis: 100 }],
          ],
        },
      },
    ],
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 320, width: "100%" }} notMerge={true} />;
}
