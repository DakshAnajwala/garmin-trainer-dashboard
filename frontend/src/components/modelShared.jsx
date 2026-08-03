// Shared between the model inspector (which reads params) and the
// custom-algorithm panel (which owns the endpoint + key, and now lives in
// Settings). Extracted so moving the panel out didn't fork these definitions.

export const PARAM_LABEL = {
  cp_watts: "Critical Power (CP)",
  w_prime_j: "W′ (anaerobic battery)",
  durability: "Durability",
  repeatability: "Repeatability",
};

export function AdvisoryBanner({ advisory }) {
  if (!advisory) return null;
  const cls =
    advisory.verdict === "improved" ? "banner-good" : advisory.verdict === "worse" ? "banner-warning" : "banner-muted";
  return (
    <div className={`verdict-banner ${cls}`}>
      <div className="verdict-headline">
        Backtest: {advisory.verdict}
        {advisory.delta_pp != null && ` (${advisory.delta_pp > 0 ? "+" : ""}${advisory.delta_pp} pp error)`}
      </div>
      <div className="verdict-detail">{advisory.detail}</div>
    </div>
  );
}
