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
    is_conversion: bool = False  # agent announcing it switched sides
    reply_to: str | None = None  # handle of the post being replied to
    parent_id: int | None = None  # id of the post being replied to
    agrees: bool | None = None  # for replies: agreeing or pushing back?
    is_rebuttal: bool = False  # author answering back to a critical reply
    llm_written: bool = False  # text was rewritten in-character by the LLM

    def to_dict(self, author: Persona, parent: "Post | None" = None) -> dict:
        return {
            "id": self.id,
            "round": self.round,
            "author_id": self.author_id,
            "author": author.name,
            "handle": author.handle,
            "avatar": author.avatar,
            "archetype": author.archetype,
            "text": self.text,
            "stance": author.stance if not self.is_event else "event",
            "likes": self.likes,
            "shares": self.shares,
            "is_event": self.is_event,
            "is_conversion": self.is_conversion,
            "reply_to": self.reply_to,
            "parent_id": self.parent_id,
            # Resolved at render time, not stored: the parent's text can be
            # rewritten by the LLM after this reply was created, and a quote
            # of a post that no longer says that is worse than no quote.
            "parent_text": parent.text if parent else None,
            "agrees": self.agrees,
            "is_rebuttal": self.is_rebuttal,
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
        # Last side (support/oppose) each agent publicly held — for conversion posts.
        self._announced_side = {p.id: self._side(p) for p in self.population}
        self._post_counter = 0
        # Round 0 snapshot = initial state, before anyone speaks.
        self.metrics_history.append(self._record_metrics())

    # ------------------------------------------------------------------ loop

    def step(self) -> list[dict]:
        """Advance one round. Returns the round's posts as dicts (newest first)."""
        self.round += 1
        new_posts: list[Post] = []

        active = [p for p in self.population if self.rng.random() < p.sociability * 0.5]
        pending_rebuttals: list[tuple[Persona, Post]] = []
        for author in active:
            text = content.write_post(author, self.topic, self.rng)
            post = Post(
                id=self._next_id(),
                round=self.round,
                author_id=author.id,
                text=text,
                opinion=author.opinion,
                virality=content.virality_score(author, self.rng),
            )
            author.posts_made += 1
            new_posts.append(post)

            hops = 2 if post.virality > 0.75 else 1
            audience = network.neighbors_within(self.graph, author.id, hops)
            replies_left = 2  # cap replies per post so threads don't explode
            for reader_id in audience:
                reader = self.population[reader_id]
                reader.remember(post.text)
                # Hub authors carry more weight; viral posts hit harder.
                weight = 0.6 + 0.4 * post.virality
                opinion.apply_influence(reader, post.opinion, weight)
                agree = abs(reader.opinion - post.opinion) < 0.4
                if agree and self.rng.random() < post.virality * 0.5:
                    post.likes += 1
                if agree and self.rng.random() < post.virality * 0.15:
                    post.shares += 1
                # Strong reactions spark replies — agents talk *to* each other.
                strongly_disagrees = abs(reader.opinion - post.opinion) > 1.0
                wants_to_reply = self.rng.random() < 0.1 * reader.expressiveness * (0.5 + post.virality)
                if replies_left > 0 and (agree or strongly_disagrees) and wants_to_reply:
                    reply = Post(
                        id=self._next_id(),
                        round=self.round,
                        author_id=reader.id,
                        text=content.write_reply(self.topic, author.handle, agree, self.rng),
                        opinion=reader.opinion,
                        virality=post.virality * 0.5,
                        reply_to=author.handle,
                        parent_id=post.id,
                        agrees=agree,
                    )
                    reader.posts_made += 1
                    author.engagement += 2  # being replied to is engagement too
                    new_posts.append(reply)
                    replies_left -= 1
                    # Criticism stings: expressive authors often fire back.
                    if not agree and self.rng.random() < 0.5 + 0.4 * author.expressiveness:
                        pending_rebuttals.append((author, reply))
            author.engagement += post.likes + post.shares * 3

        # The debate continues: authors who took criticism fire back once.
        for author, reply in pending_rebuttals[:3]:
            replier = self.population[reply.author_id]
            author.remember(reply.text)
            new_posts.append(Post(
                id=self._next_id(),
                round=self.round,
                author_id=author.id,
                text=content.write_rebuttal(self.topic, replier.handle, self.rng),
                opinion=author.opinion,
                virality=0.5,
                reply_to=replier.handle,
                parent_id=reply.id,
                agrees=False,
                is_rebuttal=True,
            ))
            author.posts_made += 1
            replier.engagement += 2

        # Agents who drifted to the opposite side since they last showed one
        # may publicly announce the change of heart.
        for agent in self.population:
            now = self._side(agent)
            last = self._announced_side[agent.id]
            if now != 0 and last != 0 and now != last and self.rng.random() < 0.6:
                new_posts.append(Post(
                    id=self._next_id(),
                    round=self.round,
                    author_id=agent.id,
                    text=content.write_conversion(self.topic, now > 0, self.rng),
                    opinion=agent.opinion,
                    virality=0.6,
                    is_conversion=True,
                ))
                agent.posts_made += 1
            if now != 0:
                self._announced_side[agent.id] = now

        self.posts.extend(new_posts)
        self.metrics_history.append(self._record_metrics())

        # Feed selection: conversions and replies are the interesting social
        # signal, so they always make the cut ahead of ordinary posts.
        conversions = [p for p in new_posts if p.is_conversion]
        replies = [p for p in new_posts if p.reply_to is not None]
        # Rebuttals are the most interesting social signal — an actual
        # back-and-forth — so they lead the reply queue.
        replies.sort(key=lambda p: not p.is_rebuttal)
        ordinary = [p for p in new_posts if not p.is_conversion and p.reply_to is None]
        ordinary.sort(key=lambda p: p.likes + p.shares * 3, reverse=True)
        shown = conversions[:2] + replies[:4] + ordinary
        return [self.serialize(p) for p in shown]

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
            id=self._next_id(),
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

    def _next_id(self) -> int:
        """Hand out a stable post id.

        Ids are assigned once at creation and never reshuffled, so a reply can
        safely hold its parent's id — an earlier version renumbered posts after
        the fact and would have left those references dangling.
        """
        post_id = self._post_counter
        self._post_counter += 1
        return post_id

    def serialize(self, post: Post) -> dict:
        """Render a post for the API, resolving its parent's current text."""
        parent = self.post_by_id(post.parent_id) if post.parent_id is not None else None
        return post.to_dict(self.population[post.author_id], parent)

    def post_by_id(self, post_id: int) -> Post | None:
        """Look up a stored post. Ids are assigned as the index in ``posts``."""
        if 0 <= post_id < len(self.posts) and self.posts[post_id].id == post_id:
            return self.posts[post_id]
        return next((p for p in self.posts if p.id == post_id), None)

    @staticmethod
    def _side(agent: Persona) -> int:
        """-1 (oppose), 0 (neutral) or +1 (support)."""
        return 1 if agent.opinion >= 0.15 else -1 if agent.opinion <= -0.15 else 0

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
