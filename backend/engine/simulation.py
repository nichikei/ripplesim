"""The simulation core: ties personas, network, opinion dynamics and content
together into a round-based loop.

Each round:
1. Agents wake up with probability = sociability.
2. Each active agent writes a post; a virality score decides how far it
   travels (1 hop for normal posts, 2 hops for viral ones).
3. Every reader's opinion updates via bounded confidence; readers may
   like/share, feeding the author's engagement score.
4. Population metrics are recorded.

Mid-simulation the caller can inject a news event ("god mode") that reaches a
fraction of the population directly and shifts the conversation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import content, network, opinion
from .personas import Persona, generate_population


@dataclass
class Post:
    id: int
    round: int
    author_id: int
    text: str
    opinion: float
    virality: float
    likes: int = 0
    shares: int = 0
    is_event: bool = False

    def to_dict(self, author: Persona) -> dict:
        return {
            "id": self.id,
            "round": self.round,
            "author": author.name,
            "handle": author.handle,
            "avatar": author.avatar,
            "archetype": author.archetype,
            "text": self.text,
            "stance": author.stance if not self.is_event else "event",
            "likes": self.likes,
            "shares": self.shares,
            "is_event": self.is_event,
        }


@dataclass
class Simulation:
    topic: str
    n_agents: int = 100
    seed: int | None = None
    bias: float = 0.0  # how favourable the seed event itself is, -1..1

    round: int = 0
    population: list[Persona] = field(default_factory=list)
    graph: network.Adjacency = field(default_factory=dict)
    posts: list[Post] = field(default_factory=list)
    metrics_history: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.population = generate_population(self.n_agents, self.rng, self.bias)
        self.graph = network.build_scale_free_graph(self.n_agents, m=3, rng=self.rng)
        # Round 0 snapshot = initial state, before anyone speaks.
        self.metrics_history.append(self._record_metrics())

    # ------------------------------------------------------------------ loop

    def step(self) -> list[dict]:
        """Advance one round. Returns the round's posts as dicts (newest first)."""
        self.round += 1
        new_posts: list[Post] = []

        active = [p for p in self.population if self.rng.random() < p.sociability * 0.5]
        for author in active:
            text = content.write_post(author, self.topic, self.rng)
            post = Post(
                id=len(self.posts) + len(new_posts),
                round=self.round,
                author_id=author.id,
                text=text,
                opinion=author.opinion,
                virality=content.virality_score(author, self.rng),
            )
            author.posts_made += 1

            hops = 2 if post.virality > 0.75 else 1
            audience = network.neighbors_within(self.graph, author.id, hops)
            for reader_id in audience:
                reader = self.population[reader_id]
                # Hub authors carry more weight; viral posts hit harder.
                weight = 0.6 + 0.4 * post.virality
                opinion.apply_influence(reader, post.opinion, weight)
                agree = abs(reader.opinion - post.opinion) < 0.4
                if agree and self.rng.random() < post.virality * 0.5:
                    post.likes += 1
                if agree and self.rng.random() < post.virality * 0.15:
                    post.shares += 1
            author.engagement += post.likes + post.shares * 3
            new_posts.append(post)

        self.posts.extend(new_posts)
        self.metrics_history.append(self._record_metrics())

        shown = sorted(new_posts, key=lambda p: p.likes + p.shares * 3, reverse=True)
        return [p.to_dict(self.population[p.author_id]) for p in shown]

    # ----------------------------------------------------------- god mode

    def inject_event(self, headline: str, impact: float, reach: float = 0.6) -> dict:
        """Broadcast a breaking-news event into the simulation.

        ``impact`` (-1..1) is the event's stance push; ``reach`` is the fraction
        of the population that sees it directly.
        """
        impact = max(-1.0, min(1.0, impact))
        touched = 0
        for agent in self.population:
            if self.rng.random() < reach:
                # Broadcast news bypasses bounded confidence (no backfire).
                opinion.apply_news_shock(agent, impact)
                touched += 1

        event_post = Post(
            id=len(self.posts),
            round=self.round,
            author_id=0,
            text=f"🗞️ BREAKING: {headline}",
            opinion=impact,
            virality=1.0,
            is_event=True,
        )
        self.posts.append(event_post)
        record = {"round": self.round, "headline": headline, "impact": impact, "reached": touched}
        self.events.append(record)
        return record

    # ------------------------------------------------------------- helpers

    def _record_metrics(self) -> dict:
        snap = opinion.snapshot_metrics(self.population)
        snap["round"] = self.round
        return snap

    def agents_summary(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "handle": p.handle,
                "avatar": p.avatar,
                "archetype": p.archetype,
                "opinion": round(p.opinion, 3),
                "followers": network.degree(self.graph, p.id),
                "engagement": p.engagement,
            }
            for p in self.population
        ]
