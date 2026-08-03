// Run: npm test  (plain node — the app has no JS test runner, and adding one
// for a handful of pure-function checks wasn't worth the dependency.)
//
// Covers the diff buffer that makes the coach's typewriter handle a stream
// *revising* what it already said, rather than only appending. The tick machine
// mirrors useTypewriter's effect exactly; if that logic changes, change it here.
import { commonPrefixLength } from "./useTypewriter.js";

let pass = 0;
let fail = 0;

const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(
    `${ok ? "PASS" : "FAIL"}  ${name}` +
      (ok ? "" : `\n   got ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`)
  );
};

eq("identical strings agree fully", commonPrefixLength("abc", "abc"), 3);
eq("pure append — the ordinary streaming case", commonPrefixLength("abc", "abcdef"), 3);
eq("revised tail agrees only up to the change", commonPrefixLength("Ride hard today", "Ride easy today"), 5);
eq("no shared prefix", commonPrefixLength("xyz", "abc"), 0);
eq("empty start", commonPrefixLength("", "abc"), 0);

/** One step of useTypewriter's tick: delete a wrong tail, else type forward. */
function simulate(shown, goal) {
  const steps = [];
  let guard = 0;
  while (shown !== goal && guard++ < 5000) {
    const agreed = commonPrefixLength(shown, goal);
    if (agreed < shown.length) shown = shown.slice(0, shown.length - 1);
    else shown = goal.slice(0, shown.length + 1);
    steps.push(shown);
  }
  return steps;
}

const appended = simulate("Ride", "Ride hard");
eq("append converges", appended.at(-1), "Ride hard");
eq(
  "append never deletes",
  appended.every((s, i) => i === 0 || s.length >= appended[i - 1].length),
  true
);

const revised = simulate("Ride hard today", "Ride easy today");
eq("revision converges", revised.at(-1), "Ride easy today");
eq(
  "revision rewinds only to the shared prefix, not to empty",
  revised.reduce((m, s) => Math.min(m, s.length), Infinity),
  5
);
eq(
  "revision never shows text belonging to neither version",
  revised.every((s) => "Ride easy today".startsWith(s) || "Ride hard today".startsWith(s)),
  true
);

eq("total replacement still terminates", simulate("abc", "xyz").at(-1), "xyz");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
