import { createContext, useContext, useEffect, useState } from "react";

// "Redacted Mode" — hides fitness-revealing numbers (FTP, power, TSS/CTL/ATL/
// Form, HRV, VO2max, weight) so the app can be shown to friends without
// revealing exactly how fit the athlete is. Heart rate, sleep, stress, body
// battery, and readiness stay visible — the athlete explicitly said HR is
// fine to show, only HRV specifically should hide alongside power/FTP/TSS.
const RedactContext = createContext({ redacted: false, toggle: () => {} });

const STORAGE_KEY = "redacted_mode";

export function RedactProvider({ children }) {
  const [redacted, setRedacted] = useState(() => localStorage.getItem(STORAGE_KEY) === "1");

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, redacted ? "1" : "0");
  }, [redacted]);

  return (
    <RedactContext.Provider value={{ redacted, toggle: () => setRedacted((r) => !r) }}>
      {children}
    </RedactContext.Provider>
  );
}

export function useRedact() {
  return useContext(RedactContext);
}

// Categories that get hidden in redacted mode.
const HIDDEN_CATEGORIES = new Set(["ftp", "power", "tss", "hrv", "vo2max", "weight", "wkg", "fitness"]);

export function redactValue(value, category, redacted) {
  if (redacted && HIDDEN_CATEGORIES.has(category)) return "•••";
  return value;
}

// For free-text that embeds watt numbers ("5 x 3min @ 244-264W") or HRV
// millisecond values ("HRV (42ms) is below your baseline (79ms)") — masks the
// numbers but keeps the sentence structure so the rest stays readable.
export function redactSensitiveText(text, redacted) {
  if (!redacted || !text) return text;
  return text
    .replace(/\d+(\.\d+)?(-\d+(\.\d+)?)?W\b/g, "•••W")
    .replace(/\d+(\.\d+)?ms\b/g, "•••ms");
}
