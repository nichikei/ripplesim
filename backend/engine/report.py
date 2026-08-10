"""Prediction report: turn a finished simulation into a human-readable verdict.

Aggregates the metrics history into a narrative summary — where opinion
started, where it ended, how polarized the society became, who drove the
conversation and which posts defined it.
"""

from __future__ import annotations

from .simulation import Simulation


def _trend_label(start: float, end: float) -> str:
    delta = end - start
    if delta > 0.15:
        return "strongly improving"
    if delta > 0.05:
        return "improving"
    if delta < -0.15:
        return "strongly deteriorating"
    if delta < -0.05:
        return "deteriorating"
    return "stable"


def _verdict(mean: float, polarization: float) -> str:
    if polarization > 0.55:
        return "DIVIDED — expect a prolonged, heated debate"
    if mean > 0.25:
        return "FAVORABLE — public opinion leans clearly positive"
    if mean < -0.25:
        return "HOSTILE — public opinion leans clearly negative"
    return "CONTESTED — no dominant narrative yet"


def build_report(sim: Simulation) -> dict:
    first, last = sim.metrics_history[0], sim.metrics_history[-1]
    trend = _trend_label(first["mean_opinion"], last["mean_opinion"])

    influencers = sorted(sim.population, key=lambda p: p.engagement, reverse=True)[:5]
    top_posts = sorted(
        (p for p in sim.posts if not p.is_event),
        key=lambda p: p.likes + p.shares * 3,
        reverse=True,
    )[:5]

    n = len(sim.population)
    support_pct = round(100 * last["counts"]["support"] / n)
    oppose_pct = round(100 * last["counts"]["oppose"] / n)

    summary = (
        f'After {sim.round} rounds and {len(sim.posts)} posts about "{sim.topic}", '
        f"sentiment is {trend}: mean stance moved from {first['mean_opinion']:+.2f} "
        f"to {last['mean_opinion']:+.2f}. {support_pct}% of agents now support, "
        f"{oppose_pct}% oppose. Polarization is at {last['polarization']:.2f}"
        + (f", after {len(sim.events)} injected event(s)." if sim.events else ".")
    )

    return {
        "topic": sim.topic,
        "rounds": sim.round,
        "total_posts": len(sim.posts),
        "verdict": _verdict(last["mean_opinion"], last["polarization"]),
        "trend": trend,
        "summary": summary,
        "initial": first,
        "final": last,
        "events": sim.events,
        "trajectory": sim.metrics_history,
        "top_influencers": [
            {
                "name": p.name,
                "handle": p.handle,
                "avatar": p.avatar,
                "archetype": p.archetype,
                "engagement": p.engagement,
                "posts": p.posts_made,
            }
            for p in influencers
        ],
        "top_posts": [p.to_dict(sim.population[p.author_id]) for p in top_posts],
    }
