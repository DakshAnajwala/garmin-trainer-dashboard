import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { colors } from "../theme";

// Power-profile grid: category bands as rows, durations as columns, one line
// per time window drawn across them.
//
// The design's whole trick is that each column is scaled to its OWN W/kg range,
// so a category band sits at the same height everywhere even though Cat 3 means
// ~12.5 W/kg at 5s and ~3.9 W/kg at 20min. That makes "my sprint is Cat 3 but my
// threshold is Cat 4" legible at a glance — which the continuous log-duration
// curve genuinely cannot show, because there everything shares one watt scale
// and the sprint end dwarfs the rest.
//
// Implementation: two stacked y-axes do the work. A category axis carries the
// band names (centred in each band, in the left gutter); a hidden value axis
// 0..bandCount carries the points. Both span the same pixels, so category i's
// centre is exactly value i+0.5 — they stay aligned for free, at any height.

// Validated with scripts/validate_palette.js: worst adjacent CVD separation
// ΔE 16.4 (deutan), above the 12 target. #ec835a warns on contrast against the
// light surface; the summary table beside the chart and the per-point markers
// are that warning's required relief, not an optional extra.
const SERIES_COLORS = {
  "42 days": colors.violet,
  "84 days": colors.critical,
  "All time": colors.serious,
};

// Quiet alternating shading so the numbers and lines carry the meaning rather
// than a rainbow. "Below Cat 5" is the one band that isn't a real Coggan
// category, so it's dimmed; every named category (Pro/UCI included) is a real
// published threshold and is shaded like one.
function bandColor(band) {
  if (!band.is_category) return "rgba(128,128,128,0.04)";
  return band.y_low % 2 === 0 ? "rgba(128,128,128,0.10)" : "rgba(128,128,128,0.03)";
}

export default function CogganChart({ profile }) {
  const grid = profile?.grid;
  const [hidden, setHidden] = useState([]);

  if (!grid?.available) {
    return <div className="empty-note">{grid?.reason || profile?.reason || "Coggan profile unavailable."}</div>;
  }

  const { columns, rows, bands, series, axis_note: axisNote, window_note: windowNote } = grid;
  const bandCount = bands.length;
  const visible = series.filter((s) => !hidden.includes(s.name));
  const colIndex = Object.fromEntries(columns.map((c, i) => [c.duration_s, i]));

  // The ladder: one W/kg label per cell, drawn as a symbol-less scatter so the
  // numbers sit inside the plot behind the lines, as in the reference.
  const ladder = {
    type: "scatter",
    symbolSize: 0,
    silent: true,
    animation: false,
    yAxisIndex: 1,
    data: rows.flatMap((r) =>
      columns.map((c) => ({
        value: [colIndex[c.duration_s], r.y],
        label: { formatter: r.values[String(c.duration_s)].toFixed(2) },
      }))
    ),
    label: {
      show: true,
      color: colors.muted,
      fontSize: 11,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    },
    markArea: {
      silent: true,
      data: bands.map((b) => [{ yAxis: b.y_low, itemStyle: { color: bandColor(b) } }, { yAxis: b.y_high }]),
    },
  };

  const lineSeries = visible.map((s) => ({
    name: s.name,
    type: "line",
    yAxisIndex: 1,
    z: 10,
    symbol: "circle",
    symbolSize: 9,
    lineStyle: { width: 2, color: SERIES_COLORS[s.name] },
    // Hollow markers: the ladder number underneath stays readable.
    itemStyle: { color: "transparent", borderColor: SERIES_COLORS[s.name], borderWidth: 2 },
    data: s.points.map((p) => ({ value: [colIndex[p.duration_s], p.y], point: p })),
  }));

  const option = {
    grid: { left: 92, right: 24, top: 48, bottom: 12 },
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const p = params.data?.point;
        if (!p) return "";
        return `<strong>${params.seriesName}</strong><br/>${p.label}: ${p.watts}W — ${p.wkg} W/kg<br/>${p.category}`;
      },
    },
    xAxis: {
      type: "category",
      position: "top",
      data: columns.map((c) => c.label),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: true, lineStyle: { color: colors.grid } },
      axisLabel: { fontSize: 14, fontWeight: 600, color: colors.muted },
    },
    yAxis: [
      {
        type: "category",
        data: bands.map((b) => b.name),
        boundaryGap: true,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: colors.grid } },
        axisLabel: { fontSize: 12, color: colors.muted, margin: 12 },
      },
      { type: "value", min: 0, max: bandCount, show: false },
    ],
    series: [ladder, ...lineSeries],
  };

  return (
    <div className="coggan-grid">
      <div className="coggan-chart">
        <div className="coggan-legend">
          {series.map((s) => {
            const off = hidden.includes(s.name);
            return (
              <button
                key={s.name}
                className={`coggan-legend-item ${off ? "off" : ""}`}
                onClick={() => setHidden((h) => (off ? h.filter((n) => n !== s.name) : [...h, s.name]))}
              >
                <span className="coggan-swatch" style={{ borderColor: SERIES_COLORS[s.name] }} />
                {s.name}
              </button>
            );
          })}
        </div>
        <ReactECharts option={option} style={{ height: bandCount * 90 + 60 }} notMerge />
        <div className="caption">{axisNote}</div>
      </div>

      <div className="coggan-summary">
        <table className="coggan-table">
          <thead>
            <tr>
              <th />
              {series.map((s) => (
                <th key={s.name} style={{ color: SERIES_COLORS[s.name] }}>
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {columns.map((c) => (
              <tr key={c.duration_s} className="data-field">
                <th title={c.note || undefined}>
                  {c.label}
                  {c.note && <span className="coggan-flag">*</span>}
                </th>
                {series.map((s) => {
                  const p = s.points.find((pt) => pt.duration_s === c.duration_s);
                  return (
                    <td key={s.name}>
                      {p ? (
                        <>
                          <strong>{p.wkg.toFixed(2)}</strong> <span className="caption">{p.category}</span>
                        </>
                      ) : (
                        <span className="caption">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="data-field">
              <th>Weight</th>
              <td colSpan={series.length}>
                <strong>{grid.weight_kg}</strong> <span className="caption">kg</span>
              </td>
            </tr>
            {profile.rider_type?.type && (
              <tr className="data-field">
                <th>Type</th>
                <td colSpan={series.length}>
                  <strong>{profile.rider_type.type}</strong>
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {columns.some((c) => c.note) && (
          <div className="caption">
            {columns
              .filter((c) => c.note)
              .map((c) => `* ${c.label}: ${c.note}.`)
              .join(" ")}
          </div>
        )}
        <div className="caption">{windowNote}</div>
      </div>
    </div>
  );
}
