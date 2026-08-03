// Run: npm test  (plain node — see useTypewriter.test.mjs for why no runner)
//
// The cache holds one person's physiology in localStorage. The tests that
// matter most here aren't about speed, they're about not handing that data to
// the wrong account.
import { readCache, writeCache, clearAllCaches } from "./cache.js";

// Minimal localStorage stand-in: node has no DOM.
class FakeStorage {
  constructor() { this.store = new Map(); }
  getItem(k) { return this.store.has(k) ? this.store.get(k) : null; }
  setItem(k, v) { this.store.set(k, String(v)); }
  removeItem(k) { this.store.delete(k); }
  get length() { return this.store.size; }
  key(i) { return [...this.store.keys()][i]; }
}
// Object.keys(localStorage) is what cache.js iterates, so the fake must expose
// its entries as own enumerable properties.
function installStorage() {
  const fake = new FakeStorage();
  globalThis.localStorage = new Proxy(fake, {
    ownKeys: (t) => [...t.store.keys()],
    getOwnPropertyDescriptor: () => ({ enumerable: true, configurable: true }),
    get: (t, p) => (typeof t[p] === "function" ? t[p].bind(t) : t[p]),
  });
  return fake;
}

let pass = 0;
let fail = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}` + (ok ? "" : `\n   got ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`));
};

installStorage();

// --- round trip ---
writeCache("user-a", "overview", { ftp: 219 });
eq("round-trips a value", readCache("user-a", "overview")?.data, { ftp: 219 });
eq("reports an age", typeof readCache("user-a", "overview")?.ageMs, "number");
eq("miss returns null", readCache("user-a", "nope"), null);

// --- the one that actually matters ---
writeCache("user-b", "overview", { ftp: 999 });
eq("user A cannot read user B's cache", readCache("user-a", "overview")?.data, { ftp: 219 });
eq("user B cannot read user A's cache", readCache("user-b", "overview")?.data, { ftp: 999 });

clearAllCaches();
eq("sign-out wipes user A", readCache("user-a", "overview"), null);
eq("sign-out wipes user B", readCache("user-b", "overview"), null);

// --- resilience ---
writeCache("user-a", "overview", { ftp: 219 });
localStorage.setItem("gtd:v1:user-a:corrupt", "{not json");
eq("corrupt entry reads as a miss, not a throw", readCache("user-a", "corrupt"), null);
eq("corrupt neighbour doesn't poison a good entry", readCache("user-a", "overview")?.data, { ftp: 219 });

// Foreign keys must survive a wipe — clearing another app's localStorage
// because we share an origin would be rude at best.
localStorage.setItem("unrelated-app-key", "keep me");
clearAllCaches();
eq("wipe leaves non-cache keys alone", localStorage.getItem("unrelated-app-key"), "keep me");

// --- oversized payloads are skipped, not stored ---
const huge = { samples: new Array(60000).fill({ power_w: 250, elapsed_sec: 1 }) };
writeCache("user-a", "big", huge);
eq("payload over the size cap is not cached", readCache("user-a", "big"), null);

// --- an old cache version must never be served to new code ---
localStorage.setItem("gtd:v0:user-a:overview", JSON.stringify({ at: Date.now(), data: { ftp: 1 } }));
writeCache("user-a", "overview", { ftp: 220 }); // triggers the sweep
eq("stale-version entries are swept on write", localStorage.getItem("gtd:v0:user-a:overview"), null);
eq("current-version entry survives the sweep", readCache("user-a", "overview")?.data, { ftp: 220 });

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
