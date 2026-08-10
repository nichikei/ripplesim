"""Opinion dynamics.

Core model: *bounded confidence* (Deffuant/Hegselmann–Krause family).
When an agent reads a post:

- If the post's stance is close enough to its own (within its openness
  threshold), the agent moves toward it. Low-conviction agents move more.
- If the stance is far outside the threshold, a small *backfire* effect pushes
  the agent slightly the other way — echoing how contrarian content often
  hardens existing beliefs.

Also provides population-level metrics (mean stance, polarization, stance
distribution) recorded every round.
"""

from __future__ import annotations

from statistics import fmean, pstdev

from .personas import Persona

BASE_LEARNING_RATE = 0.25
BACKFIRE_RATE = 0.03


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def openness_threshold(agent: Persona) -> float:
    """How far an opinion can be from the agent's own and still persuade it.

    High conviction -> narrow window (0.25); low conviction -> wide (0.85).
    """
    return 0.85 - 0.6 * agent.conviction


def apply_influence(agent: Persona, post_opinion: float, weight: float = 1.0) -> None:
    """Update ``agent.opinion`` in place after reading a post.

    ``weight`` scales the effect (e.g. viral posts or trusted hubs hit harder).
    """
    gap = post_opinion - agent.opinion
    if abs(gap) <= openness_threshold(agent):
        rate = BASE_LEARNING_RATE * (1.0 - agent.conviction) * weight
        agent.opinion = _clamp(agent.opinion + rate * gap)
    else:
        # Backfire: extreme opposing content pushes the agent away from it.
        agent.opinion = _clamp(agent.opinion - BACKFIRE_RATE * weight * (1 if gap > 0 else -1))


def apply_news_shock(agent: Persona, impact: float, weight: float = 1.0) -> None:
    """Update for *broadcast news* rather than a peer's post.

    News from outside the network is not subject to bounded confidence —
    people may discount it, but it doesn't backfire the way an extreme
    stranger's post does. Everyone drifts toward the event's implication,
    scaled by how open-minded they are.
    """
    rate = 0.3 * (1.0 - 0.7 * agent.conviction) * weight
    agent.opinion = _clamp(agent.opinion + rate * (impact - agent.opinion))


def snapshot_metrics(population: list[Persona]) -> dict:
    """Population metrics for one simulation round."""
    opinions = [p.opinion for p in population]
    counts = {"support": 0, "neutral": 0, "oppose": 0}
    for p in population:
        if p.opinion >= 0.15:
            counts["support"] += 1
        elif p.opinion > -0.15:
            counts["neutral"] += 1
        else:
            counts["oppose"] += 1
    return {
        "mean_opinion": round(fmean(opinions), 4),
        "polarization": round(pstdev(opinions), 4),  # spread of stances
        "counts": counts,
    }
