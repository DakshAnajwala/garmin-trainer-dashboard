import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// Route shape only — no basemap tiles. A real slippy map (Leaflet/Mapbox)
// would need a tile provider: an external network dependency, an API key to
// manage, and a usage policy to honour, all for a single-user dashboard whose
// other charts are already ECharts. The track alone answers "where did I ride"
// without any of that. See memory: overnight_build_assumptions_5.
export default function RouteMap({ samples }) {
  const points = samples.filter((s) => s.lat != null && s.lon != null).map((s) => [s.lon, s.lat]);

  if (points.length < 2) {
    return (
      <div className="empty-note">
        No GPS track for this activity (indoor rides have no location data).
      </div>
    );
  }

  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  const lonRange = Math.max(...lons) - Math.min(...lons);
  const latRange = Math.max(...lats) - Math.min(...lats);

  // A degree of longitude is shorter than a degree of latitude by cos(lat), so
  // plotting raw degrees on equal pixel axes stretches the route east-west.
  // Correcting the aspect ratio by that factor keeps the shape true.
  const midLat = (Math.max(...lats) + Math.min(...lats)) / 2;
  const lonScale = Math.cos((midLat * Math.PI) / 180);
  const aspect = (lonRange * lonScale) / (latRange || 1e-9);
  const height = 380;
  const width = Math.max(200, Math.min(height * aspect, 900));

  const option = {
    grid: { left: 10, right: 10, top: 10, bottom: 10 },
    xAxis: { type: "value", min: "dataMin", max: "dataMax", show: false },
    yAxis: { type: "value", min: "dataMin", max: "dataMax", show: false },
    series: [
      {
        type: "line",
        data: points,
        showSymbol: false,
        lineStyle: { color: colors.blue, width: 2 },
        // Start (green) and finish (red) markers — the one bit of orientation
        // a bare track shape can't convey on its own.
        markPoint: {
          symbolSize: 10,
          data: [
            { coord: points[0], itemStyle: { color: colors.good }, name: "Start" },
            { coord: points[points.length - 1], itemStyle: { color: colors.critical }, name: "Finish" },
          ],
          label: { show: false },
        },
      },
    ],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "none" },
      formatter: (params) => {
        const [lon, lat] = params[0].value;
        return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
      },
    },
  };

  return (
    <div className="route-map">
      <ReactECharts option={option} style={{ height, width }} notMerge={true} />
      <div className="caption">
        Route shape (no basemap). <span style={{ color: colors.good }}>●</span> start —{" "}
        <span style={{ color: colors.critical }}>●</span> finish
      </div>
    </div>
  );
}
