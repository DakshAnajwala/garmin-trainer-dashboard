export default function MetricCard({ label, value, help }) {
  return (
    <div className="metric-card">
      <div className="metric-card-label">{label}</div>
      <div className="metric-card-value">{value ?? "—"}</div>
      {help && <div className="metric-card-help">{help}</div>}
    </div>
  );
}
