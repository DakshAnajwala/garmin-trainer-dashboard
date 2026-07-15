import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

const CATEGORIES = ["Cat 5", "Cat 4", "Cat 3", "Cat 2", "Cat 1", "Pro/UCI"];

// Ordered to line up with the zone series built below: base "Below Cat 5"
// layer first, then one color per category tier, brightest/most "urgent" as
// the category gets harder to reach.
const ZONE_COLORS = [colors.grid, colors.muted, colors.blue, "#1baf7a", colors.warning, colors.serious, colors.critical];
const YOU_COLOR = colors.blueDark;

function formatDuration(s) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}min`;
  return `${Math.round(s / 3600)}hr`;
}

function categoryAt(watts, durationIdx, bands) {
  let cat = "Below Cat 5";
  for (const c of CATEGORIES) {
    if (watts >= bands[c][durationIdx].watts) cat = c;
  }
  return cat;
}

// Continuous power-duration curve (WKO/TrainingPeaks style): the athlete's
// real best power at every known duration, plotted against each Coggan
// category's threshold interpolated (log-duration space, clamped at Coggan's
// 5s/1200s domain) across that same range — rendered as stacked shaded zones
// so category boundaries read as continuous bands, not 4 disconnected bars.
export default function CogganChart({ profile }) {
  if (!profile?.available || !profile.curve?.available) {
    return <div className="empty-note">{profile?.reason || profile?.curve?.reason || "Coggan profile unavailable."}</div>;
  }

  const { durations, your_points: yourPoints, bands } = profile.curve;

  const zoneSeries = [
    { name: "Below Cat 5", values: durations.map((_, i) => bands["Cat 5"][i].watts) },
  ];
  for (let i = 1; i < CATEGORIES.length; i++) {
    const lowerCat = CATEGORIES[i - 1];
    const upperCat = CATEGORIES[i];
    zoneSeries.push({
      name: lowerCat,
      values: durations.map((_, j) => bands[upperCat][j].watts - bands[lowerCat][j].watts),
    });
  }
  zoneSeries.push({
    name: "Pro/UCI",
    values: durations.map((_, j) => bands["Pro/UCI"][j].watts * 0.15),
  });

  const series = zoneSeries.map((z, idx) => ({
    name: z.name,
    type: "line",
    data: durations.map((d, j) => [d, z.values[j]]),
    stack: "coggan-zones",
    areaStyle: { color: ZONE_COLORS[idx], opacity: 0.3 },
    lineStyle: { opacity: 0 },
    itemStyle: { color: ZONE_COLORS[idx] },
    symbol: "none",
    tooltip: { show: false },
    z: 1,
  }));

  series.push({
    name: "You",
    type: "line",
    data: yourPoints.map((p) => [p.duration_s, p.watts]),
    lineStyle: { color: YOU_COLOR, width: 2.5 },
    itemStyle: { color: YOU_COLOR, borderColor: "#fff", borderWidth: 1.5 },
    symbol: (value, params) => (yourPoints[params.dataIndex]?.unverified ? "emptyCircle" : "circle"),
    symbolSize: 9,
    z: 10,
  });

  const maxWatts = Math.max(...yourPoints.map((p) => p.watts), ...bands["Pro/UCI"].map((b) => b.watts * 1.15));

  const option = {
    legend: {
      bottom: 0,
      textStyle: { color: colors.muted },
      type: "scroll",
      data: [...CATEGORIES, "You"],
    },
    grid: { left: 55, right: 20, top: 20, bottom: 70 },
    xAxis: {
      type: "log",
      name: "Duration (log scale)",
      nameLocation: "middle",
      nameGap: 30,
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted, formatter: formatDuration },
      axisLine: { lineStyle: { color: colors.muted } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "Power (W)",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
      max: Math.ceil(maxWatts / 50) * 50,
    },
    series,
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const p = params.find((x) => x.seriesName === "You");
        if (!p) return "";
        const point = yourPoints[p.dataIndex];
        const durIdx = durations.indexOf(point.duration_s);
        const cat = categoryAt(point.watts, durIdx, bands);
        return [
          `<strong>${formatDuration(point.duration_s)}</strong>`,
          `${point.watts}W (${point.wkg} W/kg)${point.unverified ? " — unverified" : ""}`,
          `Category: ${cat}`,
        ].join("<br/>");
      },
    },
  };

  return (
    <div>
      <ReactECharts option={option} style={{ height: 380, width: "100%" }} notMerge={true} />
      {profile.weakest_zone && (
        <div className="caption">
          Your relatively weakest zone: <strong>{profile.weakest_zone}</strong>
        </div>
      )}
    </div>
  );
}
