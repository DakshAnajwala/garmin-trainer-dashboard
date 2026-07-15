import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// A real speedometer: colored zones (critical/warning/good), a needle at the
// score, and the verdict label as the center readout.
export default function ReadinessGauge({ score, verdictLabel }) {
  const value = score ?? 0;

  const option = {
    series: [
      {
        type: "gauge",
        startAngle: 210,
        endAngle: -30,
        min: 0,
        max: 100,
        splitNumber: 4,
        itemStyle: { color: colors.blue },
        progress: { show: true, width: 14 },
        axisLine: {
          lineStyle: {
            width: 14,
            color: [
              [0.25, colors.critical],
              [0.5, colors.warning],
              [0.75, colors.blue],
              [1, colors.good],
            ],
          },
        },
        pointer: { itemStyle: { color: colors.muted }, width: 5 },
        axisTick: { distance: -20, length: 6, lineStyle: { color: colors.muted, width: 1 } },
        splitLine: { distance: -22, length: 14, lineStyle: { color: colors.muted, width: 2 } },
        axisLabel: { color: colors.muted, distance: -34, fontSize: 12 },
        anchor: { show: true, showAbove: true, size: 14, itemStyle: { color: colors.muted } },
        title: { show: false },
        detail: {
          valueAnimation: true,
          offsetCenter: [0, "70%"],
          fontSize: 16,
          fontWeight: 600,
          formatter: () => verdictLabel ?? "",
          color: colors.muted,
        },
        data: [{ value }],
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 260, width: "100%" }} notMerge={true} />;
}
