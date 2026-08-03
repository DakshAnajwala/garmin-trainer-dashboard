// tabIndex=0 so the highlight is reachable by keyboard, not mouse-only. These
// are readable data surfaces rather than controls, so they stay role-less —
// announcing them as buttons would promise an action that doesn't exist.
export default function MetricCard({ label, value, help }) {
  return (
    <div className="metric-card data-field" tabIndex={0}>
      <div className="metric-card-label">{label}</div>
      <div className="metric-card-value">{value ?? "—"}</div>
      {help && <div className="metric-card-help">{help}</div>}
    </div>
  );
}
