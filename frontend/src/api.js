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
  adaptiveRecommendation: () => request("/api/plan/adaptive-recommendation"),
  planCompliance: () => request("/api/plan/compliance"),
  athlete: () => request("/api/athlete"),
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
  duplicateActivities: () => request("/api/activities/duplicates"),
  activityDevices: () => request("/api/activities/devices"),
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
  undoLog: () => request("/api/undo-log"),
  restoreUndo: (id) => request(`/api/undo-log/${id}/restore`, { method: "POST" }),
  getAeroProfile: () => request("/api/aero-profile"),
  saveAeroProfile: (profile) => request("/api/aero-profile", { method: "POST", body: JSON.stringify(profile) }),
  activitiesByDate: (start, end) => request(`/api/activities/by-date?${new URLSearchParams({ start, end })}`),
  prMarkers: (start, end) => request(`/api/trends/pr-markers?${new URLSearchParams({ start, end })}`),
  calendar: (start, end) => request(`/api/calendar?${new URLSearchParams({ start, end })}`),
  // Dated planned workouts (the real, editable plan)
  generateWeek: (day) => request(`/api/planned/generate-week?${new URLSearchParams({ day })}`, { method: "POST" }),
  savePlanned: (date, workout) => request(`/api/planned/${date}`, { method: "PUT", body: JSON.stringify(workout) }),
  clearPlanned: (date) => request(`/api/planned/${date}`, { method: "DELETE" }),
  workoutTypeCatalog: () => request("/api/planned/workout-types"),
  daySuggestions: (date, ai = false) =>
    request(`/api/planned/${date}/suggestions${ai ? "?ai=true" : ""}`),
  coachPlanDay: (date, workoutType) =>
    request(`/api/planned/${date}/coach-plan`, { method: "POST", body: JSON.stringify({ workout_type: workoutType }) }),
  trajectory: (forecastDays = 365) => request(`/api/trajectory?forecast_days=${forecastDays}`),
  ftpTestStatus: () => request("/api/ftp-test-status"),
  activityZones: (id) => request(`/api/activities/${id}/zones`),
  brief: (date) => request(`/api/brief${date ? `?date=${date}` : ""}`),
  getConstraints: () => request("/api/constraints"),
  saveConstraints: (constraints) => request("/api/constraints", { method: "POST", body: JSON.stringify(constraints) }),
  activityDecoupling: (id) => request(`/api/activities/${id}/decoupling`),
  analyzeRide: (id) => request(`/api/activities/${id}/analyze`, { method: "POST" }),
  getRideDebrief: (id) => request(`/api/activities/${id}/debrief`),
  saveRideDebrief: (id, text) => request(`/api/activities/${id}/debrief`, { method: "POST", body: JSON.stringify({ text }) }),
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
  // Streams the coach's reply, invoking onDelta as text arrives. Returns the
  // full text. Callers fall back to the non-streaming chat if this throws, so
  // a streaming failure degrades to a working chat rather than a broken one.
  chatStream: async (messages, onDelta) => {
    const token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
    const res = await fetch(`${BASE_URL}/api/coach/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ messages }),
    });
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let full = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line; keep the trailing partial.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const payload = line.slice(6);
        if (payload === "[DONE]") return full;
        const evt = JSON.parse(payload);
        if (evt.error) throw new Error(evt.error);
        if (evt.delta) {
          full += evt.delta;
          onDelta?.(full);
        }
      }
    }
    return full;
  },
  // Settings
  settings: () => request("/api/settings"),
  setSecret: (name, value) =>
    request(`/api/settings/secrets/${name}`, { method: "POST", body: JSON.stringify({ value }) }),
  revokeSecret: (name) => request(`/api/settings/secrets/${name}`, { method: "DELETE" }),
  setIntervalsAthlete: (athleteId) =>
    request("/api/settings/intervals", { method: "POST", body: JSON.stringify({ athlete_id: athleteId }) }),
  resyncToCloud: () => request("/api/settings/resync", { method: "POST" }),
  // F6: physiology model
  model: (recompute = false) => request(`/api/model${recompute ? "?recompute=true" : ""}`),
  setModelOverride: (payload) => request("/api/model/override", { method: "POST", body: JSON.stringify(payload) }),
  customAlgoStatus: () => request("/api/model/custom-algo"),
  customAlgoConfigure: (payload) => request("/api/model/custom-algo", { method: "POST", body: JSON.stringify(payload) }),
  customAlgoRevoke: () => request("/api/model/custom-algo", { method: "DELETE" }),
  customAlgoPropose: () => request("/api/model/custom-algo/propose", { method: "POST" }),
  customAlgoApply: (proposed) =>
    request("/api/model/custom-algo/apply", { method: "POST", body: JSON.stringify({ proposed }) }),
  exportModel: async () => {
    const token = auth.currentUser ? await auth.currentUser.getIdToken() : null;
    const res = await fetch(`${BASE_URL}/api/model/export`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Export failed: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "physiology_model.json";
    a.click();
    URL.revokeObjectURL(url);
  },
  // F1: race events + demand
  listEvents: () => request("/api/events"),
  createEvent: (file, fields) => {
    const form = new FormData();
    form.append("file", file);
    const qs = new URLSearchParams(fields).toString();
    return request(`/api/events?${qs}`, { method: "POST", body: form });
  },
  recomputeEvent: (id, payload = {}) =>
    request(`/api/events/${id}/recompute`, { method: "POST", body: JSON.stringify(payload) }),
  eventDemand: (id) => request(`/api/events/${id}/demand`),
  deleteEvent: (id) => request(`/api/events/${id}`, { method: "DELETE" }),
  // F8: reflow + pins
  planReflow: () => request("/api/plan/reflow"),
  setPin: (payload) => request("/api/plan/pins", { method: "POST", body: JSON.stringify(payload) }),
  // F2: prescription decision
  todayDecision: (payload) => request("/api/plan/today/decision", { method: "POST", body: JSON.stringify(payload) }),
  // F5: ask your own data
  dataQuery: (q) => request("/api/query", { method: "POST", body: JSON.stringify({ q }) }),
  powerExclusion: (activityId) => request(`/api/activities/${activityId}/power-exclusion`),
  setPowerExclusion: (activityId, payload) =>
    request(`/api/activities/${activityId}/power-exclusion`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listGear: () => request("/api/gear"),
  saveGear: (gear) => request("/api/gear", { method: "POST", body: JSON.stringify(gear) }),
  deleteGear: (id) => request(`/api/gear/${id}`, { method: "DELETE" }),
};
