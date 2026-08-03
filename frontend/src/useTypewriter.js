import { useEffect, useRef, useState } from "react";

// Types text out the way Claude does, and — the part that matters — handles the
// target text *changing* underneath the animation. A stream can revise what it
// already emitted; snapping straight to the new text loses the reader's place,
// so instead we walk back to the last character the two versions agree on and
// retype forward from there.
//
// Everything runs off a timer and mutates a ref, so a long reply never blocks
// input or scrolling: React only re-renders when the visible slice changes.

const TYPE_MS = 12;
const DELETE_MS = 6;

// Long bursts (a whole paragraph landing at once) type multiple characters per
// tick instead of slowing to a crawl — the animation should track the stream,
// not fall behind it.
function charsPerTick(pending) {
  if (pending > 400) return 12;
  if (pending > 120) return 5;
  if (pending > 40) return 2;
  return 1;
}

export function commonPrefixLength(a, b) {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a[i] === b[i]) i += 1;
  return i;
}

export function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * @param {string} target  full text known so far (grows as the stream arrives)
 * @param {boolean} enabled false renders `target` instantly (e.g. history)
 * @returns {{ text: string, typing: boolean }}
 */
export function useTypewriter(target, enabled = true) {
  const [shown, setShown] = useState(enabled ? "" : target);
  const shownRef = useRef(shown);
  const targetRef = useRef(target);

  shownRef.current = shown;
  targetRef.current = target;

  useEffect(() => {
    if (!enabled || prefersReducedMotion()) {
      setShown(target);
      return undefined;
    }

    let timer;
    const tick = () => {
      const current = shownRef.current;
      const goal = targetRef.current;

      if (current === goal) {
        timer = setTimeout(tick, TYPE_MS);
        return;
      }

      const agreed = commonPrefixLength(current, goal);

      if (agreed < current.length) {
        // The tail we already showed is now wrong — walk it back a character
        // at a time so the correction reads as a revision, not a glitch.
        setShown(current.slice(0, current.length - 1));
        timer = setTimeout(tick, DELETE_MS);
        return;
      }

      const step = charsPerTick(goal.length - current.length);
      setShown(goal.slice(0, current.length + step));
      timer = setTimeout(tick, TYPE_MS);
    };

    timer = setTimeout(tick, TYPE_MS);
    return () => clearTimeout(timer);
  }, [enabled, target]);

  return { text: shown, typing: enabled && shown !== target };
}
