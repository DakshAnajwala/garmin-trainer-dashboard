import ReactECharts from "echarts-for-react";
import { colors } from "../theme";
import { useRedact } from "../redactContext";

// Per-lap power and HR bars. One-lap activities (outdoor rides synced as a
// single lap) still render a single bar per metric.
export default function ActivitySplitsChart({ splits }) {
  const { redacted } = useRedact();
  const hasPower = splits.some((s) => s.avg_power_w != null) && !redacted;
  const labels = splits.map((s) => `Lap ${s.lap_index}`);

  const series = [
    {
      name: "Avg HR",
      type: "bar",
      data: splits.map((s) => s.avg_hr),
      itemStyle: { color: colors.critical, borderRadius: [4, 4, 0, 0] },
    },
  ];
  if (hasPower) {
    series.unshift({
      name: "Avg power",
      type: "bar",
      data: splits.map((s) => s.avg_power_w),
      itemStyle: { color: colors.blue, borderRadius: [4, 4, 0, 0] },
    });
  }

  const option = {
    legend: { bottom: 0, textStyle: { color: colors.muted } },
    grid: { left: 45, right: 20, top: 20, bottom: 50 },
    xAxis: { type: "category", data: labels, axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.muted } } },
    yAxis: { type: "value", axisLabel: { color: colors.muted }, splitLine: { lineStyle: { color: colors.grid } } },
    series,
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height: 260, width: "100%" }} notMerge={true} />;
}
