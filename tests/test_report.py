from backend.engine.report import build_report, debate_stats, faction_breakdown, key_moments
from backend.engine.simulation import Simulation
from backend.report_agent import render_markdown, strip_preamble


def finished_sim(rounds: int = 8, with_event: bool = False) -> Simulation:
    sim = Simulation(topic="Free transport for students", n_agents=100, seed=3)
    for i in range(rounds):
        sim.step()
        if with_event and i == rounds // 2:
            sim.inject_event("Auditors find a funding gap", impact=-0.8, reach=0.7)
    return sim


def test_factions_cover_every_agent():
    sim = finished_sim()
    factions = faction_breakdown(sim)
    assert sum(f["size"] for f in factions) == len(sim.population)
    # sorted by how far the group moved
    shifts = [abs(f["shift"]) for f in factions]
    assert shifts == sorted(shifts, reverse=True)


def test_key_moments_flag_injected_events():
    sim = finished_sim(with_event=True)
    moments = key_moments(sim, k=8)
    assert moments
    assert any(m["event"] for m in moments), "an injected event should surface as a key moment"


def test_debate_stats_add_up():
    sim = finished_sim()
    stats = debate_stats(sim)
    assert stats["total_posts"] == len(sim.posts)
    assert stats["agreeing_replies"] + stats["disagreeing_replies"] == stats["replies"]


def test_markdown_report_is_complete():
    md = render_markdown(build_report(finished_sim(with_event=True)))
    for section in ("# Opinion report", "## Factions", "## Key moments",
                    "## Conversation dynamics", "## Top influencers"):
        assert section in md
    assert "| Group | Size |" in md          # faction table renders
    assert md.endswith("\n")


def test_agent_narration_is_stripped_from_the_deliverable():
    raw = "Now I have enough to write the report.\n\n## Executive summary\n\nOpinion hardened."
    assert strip_preamble(raw).startswith("## Executive summary")


def test_strip_preamble_leaves_a_clean_report_untouched():
    clean = "## Executive summary\n\nOpinion hardened."
    assert strip_preamble(clean) == clean
    # and a report with no headings at all is still returned, not dropped
    assert strip_preamble("  just prose  ") == "just prose"


def test_markdown_report_includes_agent_analysis_when_present():
    md = render_markdown(build_report(finished_sim()), analysis="Opinion hardened early.")
    assert "## Analyst assessment" in md
    assert "Opinion hardened early." in md
