import { auth } from "./firebase";

// In production the built frontend is served by the same FastAPI container
// (same origin, no CORS needed) — only local dev (Vite on :5173 talking to
// uvicorn on :8000) needs an absolute cross-origin URL.
const BASE_URL = import.meta.env.PROD ? "" : "http://localhost:8000";

async function request(path, options = {}) {
  const token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      // FormData sets its own multipart Content-Type (with boundary) — the
      // browser only does this automatically if we don't set one ourselves.
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request("/api/health"),
  readiness: (date) => request(`/api/readiness${date ? `?date=${date}` : ""}`),
  snapshot: (date) => request(`/api/snapshot${date ? `?date=${date}` : ""}`),
  hrvHistory: ({ start, end, days } = {}) =>
    request(`/api/history/hrv?${new URLSearchParams(start && end ? { start, end } : { days: days ?? 30 })}`),
  readinessHistory: ({ start, end, days } = {}) =>
    request(`/api/history/readiness?${new URLSearchParams(start && end ? { start, end } : { days: days ?? 30 })}`),
  weightHistory: (days = 180) => request(`/api/weight?days=${days}`),
  logWeight: (weight_kg, date) =>
    request("/api/weight", { method: "POST", body: JSON.stringify({ weight_kg, date }) }),
  overview: (date) => request(`/api/overview${date ? `?date=${date}` : ""}`),
  weekPlan: (date) => request(`/api/plan/week${date ? `?date=${date}` : ""}`),
  todayPlan: (date) => request(`/api/plan/today${date ? `?date=${date}` : ""}`),
  getBlockWeek: () => request("/api/plan/block-week"),
  setBlockWeek: (block_week) =>
    request("/api/plan/block-week", { method: "POST", body: JSON.stringify({ block_week }) }),
  followups: () => request("/api/coach/followups"),
  analyzeDay: (date) => request(`/api/coach/analyze${date ? `?date=${date}` : ""}`, { method: "POST" }),
  chat: (messages, date) =>
    request(`/api/coach/chat${date ? `?date=${date}` : ""}`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),
  logFtp: (power_20min_w, date) =>
    request("/api/ftp", { method: "POST", body: JSON.stringify({ power_20min_w, date }) }),
  personalRecords: () => request("/api/personal-records"),
  activities: (limit = 20, includeHidden = false) =>
    request(`/api/activities?${new URLSearchParams({ limit, include_hidden: includeHidden })}`),
  deleteActivity: (id) => request(`/api/activities/${id}`, { method: "DELETE" }),
  hideJunkActivities: () => request("/api/activities/hide-junk", { method: "POST" }),
  unhideActivity: (id) => request(`/api/activities/${id}/unhide`, { method: "POST" }),
  assignActivityGear: (id, gear_id) =>
    request(`/api/activities/${id}/gear`, { method: "POST", body: JSON.stringify({ gear_id }) }),
  activitySplits: (id) => request(`/api/activities/${id}/splits`),
  listWorkouts: () => request("/api/workouts"),
  saveWorkout: (workout) => request("/api/workouts", { method: "POST", body: JSON.stringify(workout) }),
  deleteWorkout: (id) => request(`/api/workouts/${id}`, { method: "DELETE" }),
  wednesdayTemplate: () => request("/api/workouts/wednesday-template"),
  exportZwoUrl: `${BASE_URL}/api/workouts/export-zwo`,
  activityDetails: (id) => request(`/api/activities/${id}/details`),
  cogganProfile: () => request("/api/coggan-profile"),
  strengthSessions: (days = 180) => request(`/api/strength?days=${days}`),
  logStrength: (payload) => request("/api/strength", { method: "POST", body: JSON.stringify(payload) }),
  deleteStrength: (id) => request(`/api/strength/${id}`, { method: "DELETE" }),
  intervalsStatus: () => request("/api/intervals/status"),
  intervalsWellness: ({ start, end, days } = {}) =>
    request(`/api/intervals/wellness?${new URLSearchParams(start && end ? { start, end } : { days: days ?? 90 })}`),
  listGoals: () => request("/api/goals"),
  saveGoal: (goal) => request("/api/goals", { method: "POST", body: JSON.stringify(goal) }),
  deleteGoal: (id) => request(`/api/goals/${id}`, { method: "DELETE" }),
  getAeroProfile: () => request("/api/aero-profile"),
  saveAeroProfile: (profile) => request("/api/aero-profile", { method: "POST", body: JSON.stringify(profile) }),
  activitiesByDate: (start, end) => request(`/api/activities/by-date?${new URLSearchParams({ start, end })}`),
  prMarkers: (start, end) => request(`/api/trends/pr-markers?${new URLSearchParams({ start, end })}`),
  calendar: (start, end) => request(`/api/calendar?${new URLSearchParams({ start, end })}`),
  trajectory: (forecastDays = 365) => request(`/api/trajectory?forecast_days=${forecastDays}`),
  ftpTestStatus: () => request("/api/ftp-test-status"),
  activityZones: (id) => request(`/api/activities/${id}/zones`),
  activityDecoupling: (id) => request(`/api/activities/${id}/decoupling`),
  analyzeRide: (id) => request(`/api/activities/${id}/analyze`, { method: "POST" }),
  // Bypasses the JSON-parsing request() helper — this returns a file blob,
  // not JSON — but still needs the same auth header and error handling.
  exportData: async (payload) => {
    const token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
    const res = await fetch(`${BASE_URL}/api/export`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch ? filenameMatch[1] : `export.${payload.format}`;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
  importActivity: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/activities/import", { method: "POST", body: form });
  },
  listGear: () => request("/api/gear"),
  saveGear: (gear) => request("/api/gear", { method: "POST", body: JSON.stringify(gear) }),
  deleteGear: (id) => request(`/api/gear/${id}`, { method: "DELETE" }),
};
