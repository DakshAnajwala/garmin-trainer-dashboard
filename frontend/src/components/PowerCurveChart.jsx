import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function PowerCurveChart({ powerCurve, unverified }) {
  const durations = Object.keys(powerCurve).map(Number).sort((a, b) => a - b);
  const points = durations.map((d) => [d, powerCurve[d]]);
  const symbols = durations.map((d) => (unverified.includes(d) ? "emptyCircle" : "circle"));

  const option = {
    grid: { left: 55, right: 30, top: 30, bottom: 50 },
    xAxis: {
      type: "log",
      name: "Duration (s, log scale)",
      nameLocation: "middle",
      nameGap: 30,
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      axisLine: { lineStyle: { color: colors.muted } },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    yAxis: {
      type: "value",
      name: "Power (W)",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "line",
        data: points,
        lineStyle: { color: colors.blue, width: 2 },
        itemStyle: { color: colors.blue },
        symbol: (value, params) => symbols[params.dataIndex],
        symbolSize: 10,
        label: { show: true, formatter: (p) => `${p.value[1]}W`, position: "top", color: colors.muted, fontSize: 11 },
      },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (params) => `${params[0].value[0]}s: ${params[0].value[1]}W`,
    },
  };
  return <ReactECharts option={option} style={{ height: 340, width: "100%" }} notMerge={true} />;
}
