import random

import pytest

from backend.engine.network import build_scale_free_graph, neighbors_within, top_hubs
from backend.engine.opinion import apply_influence, snapshot_metrics
from backend.engine.personas import Persona, generate_population
from backend.engine.simulation import Simulation


@pytest.fixture
def rng():
    return random.Random(42)


# ---------------------------------------------------------------- personas

def test_population_size_and_bounds(rng):
    pop = generate_population(50, rng)
    assert len(pop) == 50
    for p in pop:
        assert -1.0 <= p.opinion <= 1.0
        assert 0.0 <= p.conviction <= 1.0
        assert p.handle.startswith("@")


def test_bias_shifts_population(rng):
    positive = generate_population(200, random.Random(1), bias=0.8)
    negative = generate_population(200, random.Random(1), bias=-0.8)
    mean_pos = sum(p.opinion for p in positive) / len(positive)
    mean_neg = sum(p.opinion for p in negative) / len(negative)
    assert mean_pos > mean_neg


def test_stance_buckets():
    p = Persona(0, "A", "@a", "🐟", "casual", 0.8, 0.5, 0.5, 0.5)
    assert p.stance == "strong_support"
    p.opinion = -0.8
    assert p.stance == "strong_oppose"
    p.opinion = 0.0
    assert p.stance == "neutral"


# ----------------------------------------------------------------- network

def test_graph_is_connected_and_scale_free(rng):
    n = 200
    adj = build_scale_free_graph(n, m=3, rng=rng)
    assert len(adj) == n
    # undirected: every edge appears in both directions
    for node, nbs in adj.items():
        for nb in nbs:
            assert node in adj[nb]
    # hubs should have far more connections than the median node
    degrees = sorted(len(nbs) for nbs in adj.values())
    assert degrees[-1] > 3 * degrees[n // 2]


def test_top_hubs_and_hops(rng):
    adj = build_scale_free_graph(50, m=2, rng=rng)
    hubs = top_hubs(adj, k=3)
    assert len(hubs) == 3
    one_hop = neighbors_within(adj, hubs[0], 1)
    two_hop = neighbors_within(adj, hubs[0], 2)
    assert one_hop <= two_hop
    assert hubs[0] not in two_hop


# ----------------------------------------------------------------- opinion

def test_influence_moves_toward_close_opinion():
    agent = Persona(0, "A", "@a", "🐟", "casual", 0.0, conviction=0.2,
                    sociability=0.5, expressiveness=0.5)
    apply_influence(agent, 0.4)
    assert 0.0 < agent.opinion <= 0.4


def test_backfire_on_extreme_gap():
    agent = Persona(0, "A", "@a", "🐟", "skeptic", -0.8, conviction=0.9,
                    sociability=0.5, expressiveness=0.5)
    apply_influence(agent, 0.9)  # far outside openness threshold
    assert agent.opinion < -0.8  # pushed further away


def test_snapshot_metrics_counts():
    pop = generate_population(100, random.Random(7))
    snap = snapshot_metrics(pop)
    assert sum(snap["counts"].values()) == 100
    assert -1.0 <= snap["mean_opinion"] <= 1.0


# -------------------------------------------------------------- simulation

def test_simulation_runs_and_records_metrics():
    sim = Simulation(topic="test topic", n_agents=60, seed=123)
    for _ in range(5):
        sim.step()
    assert sim.round == 5
    assert len(sim.metrics_history) == 6  # initial snapshot + 5 rounds
    assert len(sim.posts) > 0


def test_simulation_is_reproducible():
    a = Simulation(topic="repro", n_agents=40, seed=99)
    b = Simulation(topic="repro", n_agents=40, seed=99)
    for _ in range(3):
        a.step()
        b.step()
    assert a.metrics_history == b.metrics_history


def test_agents_remember_what_they_read():
    sim = Simulation(topic="memory test", n_agents=80, seed=11)
    for _ in range(4):
        sim.step()
    with_memory = [p for p in sim.population if p.memory]
    assert with_memory, "agents should accumulate memory of posts they read"
    assert all(len(p.memory) <= Persona.MEMORY_SIZE for p in sim.population)


def test_debate_produces_replies_and_rebuttals():
    sim = Simulation(topic="debate test", n_agents=120, seed=7)
    for _ in range(8):
        sim.step()

    replies = [p for p in sim.posts if p.reply_to]
    assert replies, "agents should reply to each other"
    # A reply must be able to resolve the post it answers, so the quote it
    # shows always matches what that post currently says.
    for reply in replies:
        assert reply.agrees is not None
        parent = sim.post_by_id(reply.parent_id)
        assert parent is not None, "a reply must point at a real post"
        assert sim.serialize(reply)["parent_text"] == parent.text


def test_post_ids_are_unique_and_stable():
    sim = Simulation(topic="ids", n_agents=60, seed=21)
    for _ in range(4):
        sim.step()
    sim.inject_event("Breaking", impact=-0.4)
    sim.step()
    ids = [p.id for p in sim.posts]
    assert len(ids) == len(set(ids)), "post ids must be unique"


def test_a_rewritten_post_updates_the_quote_shown_in_its_replies():
    """The LLM rewrites text after the round; stale quotes used to survive."""
    sim = Simulation(topic="quotes", n_agents=80, seed=5)
    for _ in range(4):
        sim.step()
    reply = next(p for p in sim.posts if p.parent_id is not None)
    parent = sim.post_by_id(reply.parent_id)

    parent.text = "a completely different, LLM-written sentence"
    assert sim.serialize(reply)["parent_text"] == parent.text

    rebuttals = [p for p in sim.posts if p.is_rebuttal]
    assert rebuttals, "criticised authors should answer back"
    for reb in rebuttals:
        # a rebuttal targets someone who actually replied to that author
        assert reb.agrees is False
        assert reb.reply_to != sim.population[reb.author_id].handle


def test_post_lookup_by_id_round_trips():
    sim = Simulation(topic="lookup", n_agents=50, seed=13)
    for _ in range(3):
        sim.step()
    sim.inject_event("Something happened", impact=-0.5)
    for post in sim.posts:
        assert sim.post_by_id(post.id) is post
    assert sim.post_by_id(len(sim.posts) + 99) is None


def test_event_injection_shifts_opinion():
    sim = Simulation(topic="event test", n_agents=150, seed=5)
    before = sim.metrics_history[-1]["mean_opinion"]
    record = sim.inject_event("Everything is terrible", impact=-1.0, reach=1.0)
    after = snapshot_metrics(sim.population)["mean_opinion"]
    assert record["reached"] == 150
    assert after < before
