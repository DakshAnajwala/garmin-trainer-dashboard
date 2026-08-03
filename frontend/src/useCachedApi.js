import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "./authContext";
import { readCache, writeCache } from "./cache";

// Stale-while-revalidate for API responses.
//
// Render the last known answer immediately, then refresh in the background and
// swap in the new one. Switching to a tab you've already visited becomes
// instant instead of a spinner, which is the whole point — the data usually
// hasn't changed, and when it has, it corrects itself a moment later.
//
// `fresh` is deliberately generous by default: this data changes on the scale
// of a ride, not a second, so a few minutes of staleness costs nothing real
// while a spinner on every tab switch costs attention every time.

const DEFAULT_FRESH_MS = 5 * 60 * 1000;

/**
 * @param {string} path      cache key — the API path this resource represents
 * @param {() => Promise<any>} fetcher
 * @param {{ freshMs?: number, enabled?: boolean }} [opts]
 * @returns {{ data, error, loading, refreshing, refresh }}
 *   loading    = nothing to show yet (first ever visit)
 *   refreshing = showing cached data while checking for newer
 */
export function useCachedApi(path, fetcher, { freshMs = DEFAULT_FRESH_MS, enabled = true } = {}) {
  const { user } = useAuth();
  const uid = user?.uid;

  // Seed from cache during the first render so there's no empty flash at all.
  const [data, setData] = useState(() => (uid && enabled ? readCache(uid, path)?.data ?? null : null));
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // Survives re-renders and prevents a slow response from overwriting a newer
  // one (or a signed-out user's screen).
  const activeRef = useRef(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(
    async (force) => {
      if (!enabled || !uid) return;

      const cached = readCache(uid, path);
      if (cached) setData(cached.data);
      if (!force && cached && cached.ageMs < freshMs) return; // still fresh — don't touch the network

      const token = ++activeRef.current;
      setRefreshing(true);
      try {
        const fresh = await fetcherRef.current();
        if (token !== activeRef.current) return; // superseded
        setData(fresh);
        setError(null);
        writeCache(uid, path, fresh);
      } catch (e) {
        if (token !== activeRef.current) return;
        // A failed refresh must not blank out good cached data — show the
        // stale numbers and surface the error alongside them.
        setError(e.message);
      } finally {
        if (token === activeRef.current) setRefreshing(false);
      }
    },
    [enabled, uid, path, freshMs]
  );

  useEffect(() => {
    load(false);
    return () => {
      activeRef.current += 1; // unmounted: ignore anything still in flight
    };
  }, [load]);

  return {
    data,
    error,
    loading: data === null && error === null,
    refreshing,
    refresh: () => load(true),
  };
}
