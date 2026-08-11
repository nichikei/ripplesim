"""Prediction report: turn a finished simulation into a human-readable verdict.

Aggregates the metrics history into a narrative summary — where opinion
started, where it ended, how polarized the society became, who drove the
conversation and which posts defined it.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

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


def faction_breakdown(sim: Simulation) -> list[dict]:
    """How each archetype ended up, and how far it moved."""
    groups: dict[str, list] = defaultdict(list)
    for p in sim.population:
        groups[p.archetype].append(p)

    factions = []
    for archetype, members in groups.items():
        start = fmean(p.initial_opinion for p in members)
        end = fmean(p.opinion for p in members)
        factions.append({
            "archetype": archetype,
            "size": len(members),
            "start_mean": round(start, 3),
            "end_mean": round(end, 3),
            "shift": round(end - start, 3),
            "supporters": sum(1 for p in members if p.opinion >= 0.15),
            "opponents": sum(1 for p in members if p.opinion <= -0.15),
        })
    return sorted(factions, key=lambda f: abs(f["shift"]), reverse=True)


def key_moments(sim: Simulation, k: int = 3) -> list[dict]:
    """Rounds where opinion moved most — the turning points of the story."""
    moments = []
    history = sim.metrics_history
    for prev, cur in zip(history, history[1:]):
        delta = cur["mean_opinion"] - prev["mean_opinion"]
        event = next((e for e in sim.events if e["round"] == cur["round"]), None)
        moments.append({
            "round": cur["round"],
            "shift": round(delta, 4),
            "mean_opinion": cur["mean_opinion"],
            "polarization": cur["polarization"],
            "event": event["headline"] if event else None,
        })
    return sorted(moments, key=lambda m: abs(m["shift"]), reverse=True)[:k]


def debate_stats(sim: Simulation) -> dict:
    """How much of the activity was actual conversation vs broadcasting."""
    replies = [p for p in sim.posts if p.reply_to]
    return {
        "total_posts": len(sim.posts),
        "replies": len(replies),
        "rebuttals": sum(1 for p in sim.posts if p.is_rebuttal),
        "agreeing_replies": sum(1 for p in replies if p.agrees),
        "disagreeing_replies": sum(1 for p in replies if p.agrees is False),
        "conversions": sum(1 for p in sim.posts if p.is_conversion),
    }


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
        "factions": faction_breakdown(sim),
        "key_moments": key_moments(sim),
        "debate": debate_stats(sim),
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
        "top_posts": [sim.serialize(p) for p in top_posts],
    }
