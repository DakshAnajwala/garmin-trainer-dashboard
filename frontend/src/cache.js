// Per-user response cache backed by localStorage.
//
// The backend is already fast once its Garmin/intervals caches are warm
// (measured: 0.02-0.4s), but the frontend refetched everything on every tab
// mount, so revisiting a page always paid full price. This makes a revisit
// render instantly from the last known response, then quietly refreshes in the
// background — the "stale-while-revalidate" pattern. You see numbers now, and
// they correct themselves a moment later if they moved.
//
// PRIVACY: entries are namespaced by Firebase uid and wiped on sign-out. This
// app holds one person's physiology; leaving it in localStorage for whoever
// signs in next on a shared machine would be a real leak, not a theoretical
// one. Cache reads also require the current uid, so a stale namespace can
// never be served to a different account even if a wipe were missed.

const PREFIX = "gtd";

// Bump when a cached payload's shape changes, so an old entry can never be
// handed to new code that expects new fields. Old namespaces are swept on the
// next write.
const VERSION = "v1";

const NAMESPACE = `${PREFIX}:${VERSION}:`;

// localStorage is ~5MB and shared across the whole origin. Ride sample series
// run to thousands of points, so anything big is deliberately left uncached
// rather than risking an eviction storm that breaks every other entry.
const MAX_ENTRY_BYTES = 256 * 1024;

function keyFor(uid, path) {
  return `${NAMESPACE}${uid || "anon"}:${path}`;
}

function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function readCache(uid, path) {
  try {
    const raw = localStorage.getItem(keyFor(uid, path));
    if (!raw) return null;
    const entry = safeParse(raw);
    if (!entry || entry.data === undefined) return null;
    return { data: entry.data, ageMs: Date.now() - (entry.at || 0) };
  } catch {
    return null; // private-browsing / quota-disabled localStorage: just don't cache
  }
}

export function writeCache(uid, path, data) {
  try {
    const payload = JSON.stringify({ at: Date.now(), data });
    if (payload.length > MAX_ENTRY_BYTES) return;
    sweepOldVersions();
    localStorage.setItem(keyFor(uid, path), payload);
  } catch {
    // Quota exceeded (or disabled). Drop our own entries and move on — a cache
    // that can't write is a slower app, not a broken one.
    clearAllCaches();
  }
}

/** Wipe every cached response for every user. Call on sign-out. */
export function clearAllCaches() {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith(`${PREFIX}:`)) localStorage.removeItem(k);
    }
  } catch {
    /* nothing we can do, and nothing worth breaking the app over */
  }
}

/** Drop entries written by an older cache version. */
function sweepOldVersions() {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith(`${PREFIX}:`) && !k.startsWith(NAMESPACE)) localStorage.removeItem(k);
    }
  } catch {
    /* ignore */
  }
}
