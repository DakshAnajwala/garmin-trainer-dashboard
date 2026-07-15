// `Date#toISOString()` converts to UTC, which shifts the date backward a day
// for any positive-UTC-offset timezone (e.g. UTC+8) when the local
// time is midnight. Format from local date components instead.
export function toIsoDateLocal(d) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
