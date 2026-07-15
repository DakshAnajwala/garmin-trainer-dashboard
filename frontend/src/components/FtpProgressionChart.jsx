import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

export default function FtpProgressionChart({ ftpHistory, garminFtp, targetWkg, latestWeight }) {
  const points = ftpHistory.map((t) => ({ date: t.date, ftp: t.ftp_w, label: `${t.power_20min_w}W 20min test` }));
  if (garminFtp?.ftp_watts) {
    points.push({ date: garminFtp.date, ftp: garminFtp.ftp_watts, label: "Garmin auto-estimate" });
  }

  const targetWatts = latestWeight ? Math.round(targetWkg * latestWeight[1] * 10) / 10 : null;

  const option = {
    grid: { left: 55, right: 30, top: 30, bottom: 50 },
    xAxis: {
      type: "category",
      data: points.map((p) => p.date),
      axisLabel: { color: colors.muted },
      axisLine: { lineStyle: { color: colors.muted } },
    },
    yAxis: {
      type: "value",
      name: "FTP (W)",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "line",
        data: points.map((p) => p.ftp),
        lineStyle: { color: colors.blue, width: 2 },
        itemStyle: { color: colors.blue },
        symbol: "circle",
        symbolSize: 9,
        markLine: targetWatts
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: colors.good, type: "dashed" },
              label: {
                formatter: `${targetWkg} W/kg target (${targetWatts}W)`,
                color: colors.good,
                position: "insideEndTop",
              },
              data: [{ yAxis: targetWatts }],
            }
          : undefined,
      },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const p = points[params[0].dataIndex];
        return `${p.date}<br/>${p.label}: ${p.ftp}W`;
      },
    },
  };
  return <ReactECharts option={option} style={{ height: 320, width: "100%" }} notMerge={true} />;
}
