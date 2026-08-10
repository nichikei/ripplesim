"""Persona generation: build a population of agents with distinct personalities.

Each agent gets an archetype (journalist, skeptic, fan, ...) that shapes its
initial opinion, how stubborn it is (conviction), how often it posts
(sociability) and how emotional its posts are (expressiveness).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

FIRST_NAMES = [
    "An", "Binh", "Chi", "Dung", "Giang", "Ha", "Hieu", "Huy", "Khanh", "Lan",
    "Linh", "Long", "Mai", "Minh", "Nam", "Ngoc", "Phong", "Phuong", "Quan",
    "Son", "Thao", "Trang", "Trung", "Tuan", "Vy", "Alex", "Bella", "Chris",
    "Dana", "Eli", "Finn", "Grace", "Hugo", "Ivy", "Jack", "Kira", "Leo",
    "Mia", "Noah", "Olive", "Pete", "Quinn", "Rosa", "Sam", "Tess", "Uma",
]

AVATARS = ["🐟", "🐙", "🦀", "🐢", "🦈", "🐬", "🐠", "🦑", "🐡", "🦞", "🐚", "🦭"]

# archetype -> (opinion_mu, opinion_sigma, conviction_range, sociability_range,
#               expressiveness_range, weight)
ARCHETYPES = {
    "journalist": (0.0, 0.25, (0.4, 0.7), (0.7, 0.95), (0.3, 0.6), 8),
    "expert":     (0.1, 0.30, (0.7, 0.95), (0.3, 0.6), (0.2, 0.5), 7),
    "enthusiast": (0.6, 0.25, (0.5, 0.8), (0.6, 0.9), (0.7, 0.95), 14),
    "skeptic":    (-0.55, 0.25, (0.6, 0.9), (0.5, 0.8), (0.5, 0.8), 14),
    "casual":     (0.0, 0.35, (0.2, 0.5), (0.2, 0.5), (0.3, 0.6), 30),
    "troll":      (-0.3, 0.5, (0.3, 0.6), (0.7, 0.95), (0.85, 1.0), 6),
    "optimist":   (0.4, 0.3, (0.3, 0.6), (0.4, 0.7), (0.5, 0.8), 11),
    "doomer":     (-0.4, 0.3, (0.4, 0.7), (0.4, 0.7), (0.6, 0.9), 10),
}


@dataclass
class Persona:
    """One simulated social-media user."""

    id: int
    name: str
    handle: str
    avatar: str
    archetype: str
    opinion: float        # stance on the seed topic, -1 (oppose) .. +1 (support)
    conviction: float     # 0..1, resistance to changing opinion
    sociability: float    # 0..1, probability of being active each round
    expressiveness: float # 0..1, emotional intensity of posts
    initial_opinion: float = 0.0  # where the agent started, for trajectory context
    posts_made: int = 0
    engagement: int = field(default=0)  # likes + shares received, for influence ranking
    memory: list[str] = field(default_factory=list)  # recent posts this agent read

    MEMORY_SIZE = 5

    def remember(self, post_text: str) -> None:
        """Keep a short rolling memory of what this agent has read."""
        self.memory.append(post_text)
        if len(self.memory) > self.MEMORY_SIZE:
            self.memory.pop(0)

    @property
    def stance(self) -> str:
        """Bucketed stance label used for content generation and metrics."""
        if self.opinion >= 0.55:
            return "strong_support"
        if self.opinion >= 0.15:
            return "support"
        if self.opinion > -0.15:
            return "neutral"
        if self.opinion > -0.55:
            return "oppose"
        return "strong_oppose"


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def generate_population(n: int, rng: random.Random, bias: float = 0.0) -> list[Persona]:
    """Generate ``n`` personas.

    ``bias`` shifts the whole population's initial opinion, so the caller can
    encode how favourable the seed event itself is (-1..1).
    """
    names = list(ARCHETYPES.keys())
    weights = [ARCHETYPES[a][5] for a in names]
    population: list[Persona] = []
    used_handles: set[str] = set()

    for i in range(n):
        arch = rng.choices(names, weights=weights, k=1)[0]
        mu, sigma, conv, soc, expr, _ = ARCHETYPES[arch]
        first = rng.choice(FIRST_NAMES)
        handle = f"@{first.lower()}{rng.randint(1, 999)}"
        while handle in used_handles:
            handle = f"@{first.lower()}{rng.randint(1, 9999)}"
        used_handles.add(handle)

        opinion = _clamp(rng.gauss(mu + bias * 0.4, sigma))
        population.append(
            Persona(
                id=i,
                name=first,
                handle=handle,
                avatar=rng.choice(AVATARS),
                archetype=arch,
                opinion=opinion,
                conviction=rng.uniform(*conv),
                sociability=rng.uniform(*soc),
                expressiveness=rng.uniform(*expr),
                initial_opinion=opinion,
            )
        )
    return population
