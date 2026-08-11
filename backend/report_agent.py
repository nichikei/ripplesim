"""ReportAgent — the analyst that writes the final report.

Rather than summarising a fixed blob of numbers, the agent is given *tools* to
investigate the simulation: list factions, read a specific agent's posts,
inspect a round, search the feed. It decides what to look at, then writes the
report in Markdown.

Without an API key the module still produces a complete (deterministic) report
from the same evidence — the LLM improves the narrative, it is not required.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from backend.engine.report import build_report
from backend.engine.simulation import Simulation

MAX_TOOL_ITERATIONS = 10

SYSTEM = """You are a senior public-opinion analyst. You have just been handed \
the results of a multi-agent social simulation and a set of tools to \
investigate it.

LANGUAGE: the required output language is stated in the user's message. Write \
the entire report in that language — every section heading included — and do \
not switch to any other. The section names below are descriptions of what each \
section must contain; you write the actual heading text yourself, in the \
required language.

Investigate before you write: look at the factions, read posts from the agents \
who drove the conversation, and inspect the rounds where opinion moved most. \
Use several tools; do not write the report from the summary alone.

Then write the final report in Markdown as exactly five sections, in this \
order, each opening with its own `##` heading that you name yourself:

1. An executive summary — three or four sentences: what happened and what it \
means. Lead with the outcome.
2. What drove it — the mechanics behind the movement: who influenced whom, \
which archetypes moved and which dug in, what the injected events did. Cite \
specific handles and quote short fragments of real posts as evidence.
3. The factions — a Markdown table with six columns: the group, its size, its \
starting stance, its ending stance, the shift, and your one-line reading of \
that group. Name the column headers yourself.
4. Risks and what to watch — two or three concrete things that could change \
the outcome.
5. A prediction — one paragraph: where this goes next, and one recommendation \
for someone who cares about the outcome. Commit to a call, no hedging.

Write in plain prose, no bullet-point soup, no preamble before the first \
heading. Never mention that this is a simulation of agents; write as if \
analysing a real public conversation.

Some posts are marked [template] — filler the participants did not really \
write. Never quote those. Quote only unmarked posts as evidence."""


def _fmt(x: float) -> str:
    return f"{x:+.2f}"


def strip_preamble(text: str) -> str:
    """Drop any narration the agent writes before the report itself.

    The final turn often opens with something like "Now I have enough to write
    the report." — fine as thinking-out-loud, wrong in a deliverable. The
    report proper starts at its first heading.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[i:]).strip()
    return text.strip()


# --------------------------------------------------------------- fallback

def render_markdown(report: dict, analysis: Optional[str] = None) -> str:
    """Deterministic Markdown report — used offline and as the export format."""
    f, i = report["final"], report["initial"]
    lines = [
        f"# Opinion report — {report['topic']}",
        "",
        f"*Generated {date.today().isoformat()} · {report['rounds']} rounds · "
        f"{report['total_posts']} posts*",
        "",
        f"**Verdict: {report['verdict']}**",
        "",
        report["summary"],
        "",
    ]

    if analysis:
        lines += ["## Analyst assessment", "", analysis, ""]

    lines += [
        "## Factions",
        "",
        "| Group | Size | Start | End | Shift |",
        "|---|---:|---:|---:|---:|",
    ]
    for fa in report["factions"]:
        lines.append(
            f"| {fa['archetype']} | {fa['size']} | {_fmt(fa['start_mean'])} | "
            f"{_fmt(fa['end_mean'])} | {_fmt(fa['shift'])} |"
        )

    lines += ["", "## Key moments", ""]
    for m in report["key_moments"]:
        event = f" — event: *{m['event']}*" if m["event"] else ""
        lines.append(
            f"- **Round {m['round']}**: mean stance {_fmt(m['mean_opinion'])} "
            f"(shift {_fmt(m['shift'])}), polarization {m['polarization']:.2f}{event}"
        )

    d = report["debate"]
    lines += [
        "",
        "## Conversation dynamics",
        "",
        f"- {d['replies']} replies ({d['agreeing_replies']} agreeing, "
        f"{d['disagreeing_replies']} pushing back) and {d['rebuttals']} rebuttals",
        f"- {d['conversions']} agents publicly changed sides",
        f"- Final split: {f['counts']['support']} support · "
        f"{f['counts']['neutral']} neutral · {f['counts']['oppose']} oppose",
        f"- Mean stance moved {_fmt(i['mean_opinion'])} → {_fmt(f['mean_opinion'])}, "
        f"polarization {f['polarization']:.2f}",
        "",
        "## Top influencers",
        "",
    ]
    for p in report["top_influencers"]:
        lines.append(
            f"- **{p['name']}** ({p['handle']}, {p['archetype']}) — "
            f"{p['engagement']} engagement across {p['posts']} posts"
        )

    lines += ["", "## Most engaging posts", ""]
    for p in report["top_posts"][:5]:
        lines.append(f'- {p["handle"]} ({p["stance"]}): "{p["text"]}" — ❤️ {p["likes"]}')

    return "\n".join(lines) + "\n"


# ------------------------------------------------------------ the agent

class ReportAgent:
    """Tool-using analyst. Falls back to the deterministic report on failure."""

    def __init__(self, client, model: str) -> None:
        self.client = client
        self.model = model

    def _build_tools(self, sim: Simulation, report: dict) -> list:
        from anthropic import beta_tool

        @beta_tool
        def list_factions() -> str:
            """List every archetype group with its size and how far its average
            stance moved during the simulation."""
            rows = [
                f"{f['archetype']}: n={f['size']}, start={_fmt(f['start_mean'])}, "
                f"end={_fmt(f['end_mean'])}, shift={_fmt(f['shift'])}, "
                f"{f['supporters']} support / {f['opponents']} oppose"
                for f in report["factions"]
            ]
            return "\n".join(rows)

        @beta_tool
        def read_agent_posts(handle: str) -> str:
            """Read what one agent posted, and how its stance changed.

            Args:
                handle: The agent's handle, e.g. "@mai123".
            """
            handle = handle if handle.startswith("@") else "@" + handle
            agent = next((p for p in sim.population if p.handle == handle), None)
            if agent is None:
                return f"No agent with handle {handle}."
            posts = [p for p in sim.posts if p.author_id == agent.id]
            head = (
                f"{agent.name} ({agent.handle}), {agent.archetype}; stance "
                f"{_fmt(agent.initial_opinion)} -> {_fmt(agent.opinion)}; "
                f"conviction {agent.conviction:.2f}; {len(posts)} posts."
            )
            body = "\n".join(
                f'R{p.round}{" (reply to " + p.reply_to + ")" if p.reply_to else ""}: '
                f'"{p.text}"{"" if p.llm_written else " [template]"}'
                for p in posts[:12]
            )
            return head + ("\n" + body if body else "")

        @beta_tool
        def inspect_round(round_number: int) -> str:
            """Inspect one round: its metrics, any injected event, and its
            most-engaging posts.

            Args:
                round_number: Which round to inspect (1-based).
            """
            metrics = next(
                (m for m in sim.metrics_history if m["round"] == round_number), None
            )
            if metrics is None:
                return f"Round {round_number} is outside this simulation."
            event = next((e for e in sim.events if e["round"] == round_number), None)
            posts = sorted(
                (p for p in sim.posts if p.round == round_number),
                key=lambda p: p.likes + p.shares * 3,
                reverse=True,
            )[:6]
            lines = [
                f"Round {round_number}: mean {_fmt(metrics['mean_opinion'])}, "
                f"polarization {metrics['polarization']:.2f}, counts {metrics['counts']}"
            ]
            if event:
                lines.append(
                    f'Injected event: "{event["headline"]}" '
                    f'(impact {event["impact"]:+.1f}, reached {event["reached"]} agents)'
                )
            for p in posts:
                author = sim.population[p.author_id]
                mark = "" if p.llm_written else " [template]"
                lines.append(f'{author.handle}: "{p.text}" (❤️{p.likes}){mark}')
            return "\n".join(lines)

        @beta_tool
        def search_posts(keyword: str, limit: int = 8) -> str:
            """Search the feed for posts containing a keyword.

            Args:
                keyword: Text to search for, case-insensitive.
                limit: Maximum number of posts to return.
            """
            needle = keyword.lower()
            hits = [p for p in sim.posts if needle in p.text.lower()][: max(1, min(limit, 20))]
            if not hits:
                return f'No posts mention "{keyword}".'
            return "\n".join(
                f'R{p.round} {sim.population[p.author_id].handle}: "{p.text}"'
                f'{"" if p.llm_written else " [template]"}'
                for p in hits
            )

        return [list_factions, read_agent_posts, inspect_round, search_posts]

    # ------------------------------------------------------------- run

    def write(self, sim: Simulation, report: dict,
              language: str = "English") -> Optional[str]:
        """Investigate the simulation and return the report as Markdown."""
        brief = (
            f"WRITE THE ENTIRE REPORT IN {language.upper()}.\n\n"
            f"Topic: {report['topic']}\n"
            f"Rounds: {report['rounds']} · posts: {report['total_posts']}\n"
            f"Verdict: {report['verdict']} (trend: {report['trend']})\n"
            f"Mean stance {_fmt(report['initial']['mean_opinion'])} -> "
            f"{_fmt(report['final']['mean_opinion'])}, "
            f"polarization {report['final']['polarization']:.2f}\n"
            f"Final counts: {report['final']['counts']}\n"
            f"Debate: {report['debate']}\n"
            f"Injected events: {report['events'] or 'none'}\n"
            "Top influencers: "
            + ", ".join(f"{p['handle']} ({p['archetype']})" for p in report["top_influencers"])
            + "\nKey moments: "
            + "; ".join(
                f"round {m['round']} shift {_fmt(m['shift'])}" for m in report["key_moments"]
            )
            + f"\n\nInvestigate with the tools, then write the report in {language}."
        )

        from backend.llm import supports_effort

        kwargs: dict = {}
        if supports_effort(self.model):
            kwargs["output_config"] = {"effort": "medium"}

        try:
            runner = self.client.beta.messages.tool_runner(
                model=self.model,
                max_tokens=12000,  # room for thinking plus a multi-section report
                system=SYSTEM,
                tools=self._build_tools(sim, report),
                messages=[{"role": "user", "content": brief}],
                **kwargs,
            )
            last = None
            for iteration, message in enumerate(runner):
                last = message
                if iteration >= MAX_TOOL_ITERATIONS:
                    break
            if last is None or last.stop_reason == "refusal":
                return None
            from backend.llm import normalize_text

            text = strip_preamble(
                normalize_text("\n".join(b.text for b in last.content if b.type == "text"))
            )
            return text or None
        except Exception:
            return None
