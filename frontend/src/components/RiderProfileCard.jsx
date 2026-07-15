import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// Radar of the four rider archetypes, with the dominant type called out.
export default function RiderProfileCard({ profile }) {
  if (!profile?.type) {
    return <div className="empty-note">{profile?.note || "No rider profile available yet."}</div>;
  }

  const labels = Object.keys(profile.scores);
  const values = labels.map((l) => profile.scores[l]);
  const maxVal = Math.max(1.2, ...values);

  const option = {
    radar: {
      indicator: labels.map((l) => ({ name: l, max: maxVal })),
      axisName: { color: colors.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: colors.grid } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: colors.grid } },
    },
    series: [
      {
        type: "radar",
        data: [
          {
            value: values,
            areaStyle: { color: "rgba(42,120,214,0.25)" },
            lineStyle: { color: colors.blue },
            itemStyle: { color: colors.blue },
          },
        ],
      },
    ],
  };

  return (
    <div className="rider-profile">
      <div className="rider-profile-headline">
        You ride like a <strong>{profile.type}</strong>
      </div>
      <ReactECharts option={option} style={{ height: 280, width: "100%" }} notMerge={true} />
      <div className="caption">{profile.note}</div>
    </div>
  );
}
