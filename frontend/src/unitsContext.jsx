import { createContext, useContext, useEffect, useState } from "react";

// Display-only preference — the backend always speaks metric (kg, km, W);
// this only affects what's rendered, mirroring redactContext's pattern.
// Scoped to the highest-visibility surfaces (weight, ride distances) rather
// than every chart in the app — a full sweep of every W/kg, temperature and
// distance display across all views is a much larger undertaking than this
// pass justifies; see batch_8 assumptions for what's covered vs not.
const UnitsContext = createContext({ imperial: false, toggle: () => {} });

const STORAGE_KEY = "units_imperial";

export function UnitsProvider({ children }) {
  const [imperial, setImperial] = useState(() => localStorage.getItem(STORAGE_KEY) === "1");

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, imperial ? "1" : "0");
  }, [imperial]);

  return (
    <UnitsContext.Provider value={{ imperial, toggle: () => setImperial((v) => !v) }}>
      {children}
    </UnitsContext.Provider>
  );
}

export function useUnits() {
  return useContext(UnitsContext);
}

const KG_TO_LB = 2.20462;
const KM_TO_MI = 0.621371;

export function formatWeight(kg, imperial) {
  if (kg == null) return "—";
  return imperial ? `${(kg * KG_TO_LB).toFixed(1)} lb` : `${kg.toFixed(1)} kg`;
}

export function formatDistanceKm(km, imperial) {
  if (km == null) return "—";
  return imperial ? `${(km * KM_TO_MI).toFixed(1)} mi` : `${km.toFixed(1)} km`;
}

export function formatDistanceM(meters, imperial) {
  if (!meters) return "—";
  return formatDistanceKm(meters / 1000, imperial);
}
