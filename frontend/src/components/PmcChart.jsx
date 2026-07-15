import ReactECharts from "echarts-for-react";
import { colors, FORM_ZONES, formZoneFor } from "../theme";
import { toIsoDateLocal } from "../dateUtils";

// Standard Coggan PMC exponentially-weighted decay (42-day CTL, 7-day ATL),
// projected forward assuming zero further training stress — the same
// convention intervals.icu's own extrapolation uses.
function extrapolate(records, days) {
  if (!records.length || !days) return [];
  const last = records[records.length - 1];
  let ctl = last.ctl;
  let atl = last.atl;
  let d = new Date(last.date + "T00:00:00");
  const out = [];
  for (let i = 1; i <= days; i++) {
    d = new Date(d);
    d.setDate(d.getDate() + 1);
    ctl = ctl + (0 - ctl) / 42;
    atl = atl + (0 - atl) / 7;
    out.push({
      date: toIsoDateLocal(d),
      ctl: Math.round(ctl * 10) / 10,
      atl: Math.round(atl * 10) / 10,
      form: Math.round((ctl - atl) * 10) / 10,
      projected: true,
    });
  }
  return out;
}

export default function PmcChart({ records, extrapolateDays = 0, activitiesByDate = {}, prMarkers = {} }) {
  const projected = extrapolate(records, extrapolateDays);
  const all = [...records, ...projected];
  const dates = all.map((r) => r.date);
  const splitIdx = records.length - 1; // last real index; projected starts after

  // Build CTL/ATL/Form as two segments each (real solid, projected dashed) so
  // the dash pattern only applies to the extrapolated tail. Overlapping the
  // split index in both arrays keeps the line visually connected.
  const ctlReal = all.map((r, i) => (i <= splitIdx ? r.ctl : null));
  const ctlProj = all.map((r, i) => (i >= splitIdx ? r.ctl : null));
  const atlReal = all.map((r, i) => (i <= splitIdx ? r.atl : null));
  const atlProj = all.map((r, i) => (i >= splitIdx ? r.atl : null));
  const formReal = all.map((r, i) => (i <= splitIdx ? r.form : null));
  const formProj = all.map((r, i) => (i >= splitIdx ? r.form : null));

  const FORM_SERIES_INDICES = [4, 5]; // "Form" and "Form — projected" below, kept in sync manually

  const pieces = FORM_ZONES.map((z, i) => ({
    min: i === 0 ? -Infinity : FORM_ZONES[i - 1].max,
    max: z.max,
    color: z.color,
  }));

  const series = [
    {
      name: "Fitness (CTL)",
      type: "line",
      data: ctlReal,
      lineStyle: { color: colors.blue, width: 2 },
      itemStyle: { color: colors.blue },
      symbol: "none",
    },
    {
      name: "Fitness (CTL) — projected",
      type: "line",
      data: ctlProj,
      lineStyle: { color: colors.blue, width: 2, type: "dashed", opacity: 0.6 },
      itemStyle: { color: colors.blue },
      symbol: "none",
      tooltip: { show: false },
    },
    {
      name: "Fatigue (ATL)",
      type: "line",
      data: atlReal,
      lineStyle: { color: colors.violet, width: 2 },
      itemStyle: { color: colors.violet },
      symbol: "none",
    },
    {
      name: "Fatigue (ATL) — projected",
      type: "line",
      data: atlProj,
      lineStyle: { color: colors.violet, width: 2, type: "dashed", opacity: 0.6 },
      itemStyle: { color: colors.violet },
      symbol: "none",
      tooltip: { show: false },
    },
    { name: "Form", type: "line", data: formReal, lineStyle: { width: 2.5 }, symbol: "none" },
    {
      name: "Form — projected",
      type: "line",
      data: formProj,
      lineStyle: { width: 2.5, type: "dashed", opacity: 0.6 },
      symbol: "none",
      tooltip: { show: false },
    },
  ];

  const option = {
    legend: {
      bottom: 24,
      textStyle: { color: colors.muted },
      data: ["Fitness (CTL)", "Fatigue (ATL)", "Form"],
    },
    grid: { left: 50, right: 20, top: 20, bottom: 96 },
    xAxis: {
      type: "category",
      data: dates,
      axisLabel: { color: colors.muted },
      axisLine: { lineStyle: { color: colors.muted } },
      axisPointer: { label: { backgroundColor: colors.blue } },
    },
    yAxis: {
      type: "value",
      name: "CTL / ATL / Form",
      nameTextStyle: { color: colors.muted },
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.grid } },
    },
    visualMap: {
      show: false,
      seriesIndex: FORM_SERIES_INDICES,
      dimension: 1,
      pieces,
    },
    series,
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const idx = params[0].dataIndex;
        const row = all[idx];
        if (!row) return "";
        const round1 = (v) => (v == null ? v : Math.round(v * 10) / 10);
        const lines = [`<strong>${row.date}${row.projected ? " (projected)" : ""}</strong>`];
        lines.push(`Fitness (CTL): ${round1(row.ctl)}`);
        lines.push(`Fatigue (ATL): ${round1(row.atl)}`);
        const zone = formZoneFor(row.form);
        lines.push(`Form: ${round1(row.form)} <span style="color:${zone.color}">(${zone.label})</span>`);

        const acts = activitiesByDate[row.date];
        if (acts?.length) {
          lines.push("<hr style='opacity:0.2;margin:4px 0'/>");
          for (const a of acts) {
            const dur = a.duration_sec ? `${Math.round(a.duration_sec / 60)}min` : "";
            lines.push(`${a.name} — ${dur}`);
          }
        }
        const marker = prMarkers[row.date];
        if (marker?.new_ftp_watts) lines.push(`<span style="color:${colors.good}">🎉 New FTP: ${marker.new_ftp_watts}W</span>`);
        if (marker?.new_lactate_threshold_hr) {
          lines.push(`<span style="color:${colors.good}">🎉 New threshold HR: ${marker.new_lactate_threshold_hr}bpm</span>`);
        }
        return lines.join("<br/>");
      },
    },
  };

  return <ReactECharts option={option} style={{ height: 380, width: "100%" }} notMerge={true} />;
}
