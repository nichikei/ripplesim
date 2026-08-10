"""Social graph construction.

Real social networks are *scale-free*: most users have few followers while a
handful of hubs have many. We reproduce that with the Barabási–Albert
preferential-attachment process, implemented from scratch (no networkx):
each new node connects to ``m`` existing nodes, chosen with probability
proportional to their current degree.

The graph is undirected and stored as an adjacency dict {node: set(neighbors)}.
An edge means the two agents see each other's posts.
"""

from __future__ import annotations

import random

Adjacency = dict[int, set[int]]


def build_scale_free_graph(n: int, m: int, rng: random.Random) -> Adjacency:
    """Build a Barabási–Albert graph with ``n`` nodes and ``m`` edges per new node."""
    if n < 1:
        return {}
    m = max(1, min(m, max(1, n - 1)))

    adj: Adjacency = {i: set() for i in range(n)}
    # Seed: a small complete core of m+1 nodes so early picks have degree > 0.
    core = min(m + 1, n)
    for i in range(core):
        for j in range(i + 1, core):
            adj[i].add(j)
            adj[j].add(i)

    # repeated_nodes holds every endpoint once per degree -> sampling from it
    # IS preferential attachment, in O(1) per draw.
    repeated_nodes: list[int] = []
    for node in range(core):
        repeated_nodes.extend([node] * len(adj[node]))

    for new_node in range(core, n):
        targets: set[int] = set()
        while len(targets) < m:
            targets.add(rng.choice(repeated_nodes))
        for t in targets:
            adj[new_node].add(t)
            adj[t].add(new_node)
            repeated_nodes.extend([new_node, t])

    return adj


def degree(adj: Adjacency, node: int) -> int:
    return len(adj[node])


def top_hubs(adj: Adjacency, k: int = 5) -> list[int]:
    """Return the ``k`` best-connected nodes (the network's influencers)."""
    return sorted(adj, key=lambda node: len(adj[node]), reverse=True)[:k]


def neighbors_within(adj: Adjacency, node: int, hops: int) -> set[int]:
    """All nodes reachable from ``node`` within ``hops`` edges (excluding itself)."""
    seen = {node}
    frontier = {node}
    for _ in range(hops):
        frontier = {nb for cur in frontier for nb in adj[cur]} - seen
        seen |= frontier
    return seen - {node}
