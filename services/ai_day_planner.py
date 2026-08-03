"""The AI layer on top of the deterministic day-planner.

Per the architecture decision: the deterministic planner (services/day_planner.py)
already picks a real type and a real reason from real signals, using zero AI —
that's what keeps "Let my coach plan for me" working while the Anthropic key is
invalid. This module only RE-RANKS that choice (Claude may agree or pick a
different type from the same catalog) and writes a warmer, more specific
rationale. It never invents a type outside services/workout_types.WORKOUT_TYPES,
and it never blocks the feature — any failure here falls back to the
deterministic pick untouched.

Claude's service only returns plain text (no structured output / tool use), so
the response is parsed with a strict, narrow contract: a first line naming the
chosen type, then free text. Anything that doesn't parse cleanly is treated
exactly like an API failure — discarded, not guessed at.
"""
from __future__ import annotations

from typing import Any, Optional

import anthropic

from config.settings import settings
from services import claude_analyzer
from services.workout_types import WORKOUT_TYPES, label_for

#: Shown in the UI whenever the AI layer couldn't run — a concrete next step,
#: not a vague error, since the fix is a five-second Settings change.
UNAVAILABLE_MESSAGE = "Coaching notes need a valid Anthropic key (Settings → Connections)."

_TYPE_LIST = ", ".join(WORKOUT_TYPES)


def _client_or_none() -> Optional[anthropic.Anthropic]:
    if not settings.anthropic_api_key or settings.anthropic_api_key == "sk-ant-placeholder":
        return None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _parse_response(text: str) -> Optional[tuple[str, str]]:
    """Strict contract: first non-empty line is exactly one of WORKOUT_TYPES,
    everything after is the rationale. Anything else is a parse failure, not
    a best-effort guess — a wrong type here would contradict workout_types'
    own guarantee that only catalog types ever reach the builder."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    candidate = lines[0].lower().replace("type:", "").strip()
    if candidate not in WORKOUT_TYPES:
        return None
    rationale = " ".join(lines[1:]).strip()
    return candidate, rationale or None


def enrich(
    deterministic_type: str,
    deterministic_reason: str,
    week_summary: str,
    weakest_zone: Optional[str],
    requested_type: Optional[str],
) -> dict[str, Any]:
    """Ask Claude to confirm or re-pick the type, from the SAME catalog, and
    write the rationale in its coaching voice.

    `requested_type` is not None when the athlete explicitly chose a type
    (rather than "decide for me") — in that case the AI is only asked to
    explain the choice in context, not override it, since the athlete already
    made the decision.

    Always returns a usable result: `type` and `reason` are populated with the
    deterministic values whenever the AI path fails for any reason, so a
    caller never needs a second fallback branch.
    """
    client = _client_or_none()
    if client is None:
        return {
            "type": deterministic_type, "reason": deterministic_reason,
            "ai_used": False, "ai_unavailable_message": UNAVAILABLE_MESSAGE,
        }

    if requested_type:
        instruction = (
            f"The athlete asked specifically for a '{requested_type}' session today. Don't change the type — "
            f"just write one short, specific, encouraging sentence explaining why this type makes sense given "
            f"the context below. Respond with exactly: the word '{requested_type}' on the first line, then your "
            f"sentence on the next line."
        )
    else:
        instruction = (
            f"Pick the single best workout type for today from exactly this list: {_TYPE_LIST}. "
            f"The deterministic planner suggests '{deterministic_type}' because: {deterministic_reason} "
            "You may agree or pick a different one from the list if the week's context below suggests "
            "otherwise. Respond with exactly: the chosen type (one word from the list, lowercase) on the "
            "first line, then one short, specific, encouraging sentence of rationale on the next line. "
            "Nothing else — no preamble, no markdown."
        )

    context = (
        f"Weakest zone on the power profile: {weakest_zone or 'unknown'}.\n"
        f"This week so far: {week_summary}\n\n{instruction}"
    )

    try:
        text = claude_analyzer._send(
            model=settings.anthropic_model,
            max_tokens=150,
            system=(
                "You are a data-driven cycling coach choosing today's workout type. "
                "Follow the response format exactly — it is parsed by code, not read by a human first."
            ),
            messages=[{"role": "user", "content": context}],
        )
    except RuntimeError as exc:
        # claude_analyzer._send already translates auth/API errors into a
        # readable RuntimeError; the day-planner just needs to know it failed.
        return {
            "type": deterministic_type, "reason": deterministic_reason,
            "ai_used": False, "ai_unavailable_message": str(exc),
        }
    except Exception:
        return {
            "type": deterministic_type, "reason": deterministic_reason,
            "ai_used": False, "ai_unavailable_message": UNAVAILABLE_MESSAGE,
        }

    parsed = _parse_response(text)
    if parsed is None:
        return {
            "type": deterministic_type, "reason": deterministic_reason,
            "ai_used": False, "ai_unavailable_message": "Coach response couldn't be parsed — using the deterministic pick.",
        }

    chosen_type, ai_reason = parsed
    if requested_type and chosen_type != requested_type:
        # The AI must not override an explicit athlete choice — that's not
        # what it was asked to do, regardless of what it returned.
        chosen_type = requested_type

    return {
        "type": chosen_type,
        "reason": ai_reason or deterministic_reason,
        "ai_used": True,
        "ai_unavailable_message": None,
    }
