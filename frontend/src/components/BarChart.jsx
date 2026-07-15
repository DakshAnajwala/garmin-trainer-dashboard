import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function BarChart({ categories, values, seriesName = "", height = 260, colorList }) {
  const option = {
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: colors.muted } },
      axisLabel: { color: colors.muted },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        name: seriesName,
        type: "bar",
        data: values,
        itemStyle: {
          color: (params) => (colorList ? colorList[params.dataIndex % colorList.length] : colors.blue),
          borderRadius: [4, 4, 0, 0],
        },
        barMaxWidth: 40,
      },
    ],
    tooltip: { trigger: "axis" },
  };
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge={true} />;
}
