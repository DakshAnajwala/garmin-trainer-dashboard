import { useState } from "react";
import ReactECharts from "echarts-for-react";
import { api } from "../api";
import { colors } from "../theme";
import { useRedact } from "../redactContext";

// F5: ask your own data. One box, one sentence back, one small chart when the
// answer has a shape worth seeing. Deterministic parser — same words, same
// answer, and your training history never leaves the machine.

function MiniChart({ chart }) {
  if (!chart?.points?.length || chart.points.length < 2) return null;
  return (
    <ReactECharts
      style={{ height: 160 }}
      option={{
        grid: { left: 48, right: 16, top: 24, bottom: 24 },
        xAxis: { type: "category", data: chart.points.map((p) => p[0]), axisLabel: { color: colors.muted, fontSize: 10 } },
        yAxis: { type: "value", name: chart.unit, scale: true, axisLabel: { color: colors.muted } },
        tooltip: { trigger: "axis" },
        series: [{ type: "line", data: chart.points.map((p) => p[1]), showSymbol: true, symbolSize: 6, lineStyle: { width: 2, color: colors.blue }, itemStyle: { color: colors.blue } }],
      }}
    />
  );
}

export default function QueryBox() {
  const { redacted } = useRedact();
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    if (!q.trim() || busy) return;
    setBusy(true);
    try {
      setResult(await api.dataQuery(q));
    } catch (e) {
      setResult({ answer: `Couldn't run that: ${e.message}`, chart: null });
    } finally {
      setBusy(false);
    }
  };

  if (redacted) return null; // answers are raw numbers — hidden in redacted mode

  return (
    <div className="exclusion-panel">
      <div className="chat-input-row">
        <input
          type="text"
          placeholder='Ask your data — "20 min power at 500 kJ vs last spring", "distance in june", "hrv last 30 days"...'
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
        />
        <button onClick={ask} disabled={busy}>
          {busy ? "..." : "Ask"}
        </button>
      </div>
      {result && (
        <>
          <div className="adaptive-rec-text" style={{ fontSize: 14 }}>
            {result.answer}
            {result.cached && <span className="caption"> (cached)</span>}
          </div>
          <MiniChart chart={result.chart} />
          {result.compare_chart && <MiniChart chart={result.compare_chart} />}
        </>
      )}
    </div>
  );
}
