"""LLM services: the "minds" behind the agents, powered by the Anthropic API.

Design for cost and latency:
- The numeric simulation always runs on its own (opinions, spread, metrics).
- The LLM only writes the text of posts that actually appear in the feed
  (~10 per round instead of ~300), generated concurrently.
- Everything degrades gracefully: no key / no package / API error -> the
  template text produced by the engine is kept.

    export ANTHROPIC_API_KEY=sk-ant-...
    export RIPPLESIM_MODEL=claude-opus-5   # optional override
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from backend.engine.personas import Persona
from backend.engine.simulation import Simulation

DEFAULT_MODEL = "claude-opus-5"
MAX_LLM_POSTS_PER_ROUND = 10

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env_file() -> None:
    """Load KEY=value pairs from a local .env (git-ignored) if present.

    Real environment variables always win, so this is a convenience for local
    development, not an override.
    """
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

STANCE_DESC = {
    "strong_support": "strongly supports it and is genuinely excited",
    "support": "cautiously supports it",
    "neutral": "is undecided and curious",
    "oppose": "is skeptical and unconvinced",
    "strong_oppose": "strongly opposes it and is upset about it",
}


class LlmService:
    """Wraps the Anthropic client with persona-aware helpers."""

    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = os.environ.get("RIPPLESIM_MODEL", DEFAULT_MODEL)
        self.pool = ThreadPoolExecutor(max_workers=8)

    @classmethod
    def create(cls) -> Optional["LlmService"]:
        load_env_file()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        return cls()

    # ------------------------------------------------------------ plumbing

    def _complete(self, system: str, user: str, max_tokens: int = 500,
                  effort: str = "low") -> Optional[str]:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                output_config={"effort": effort},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if response.stop_reason == "refusal":
                return None
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text.strip() or None
        except Exception:
            return None

    @staticmethod
    def _persona_card(persona: Persona, topic: str) -> str:
        memory = "\n".join(f"- {m}" for m in persona.memory[-4:]) or "- (nothing yet)"
        return (
            f"You are {persona.name} ({persona.handle}), a '{persona.archetype}' "
            f"on a social network. The hot topic is: {topic}.\n"
            f"You currently {STANCE_DESC[persona.stance]} "
            f"(stance {persona.opinion:+.2f} on a -1..1 scale; "
            f"you started at {persona.initial_opinion:+.2f}).\n"
            f"Posts you recently read:\n{memory}\n"
            "Stay fully in character. Write casual social-media prose in your "
            "own voice; never mention being an AI or a simulation."
        )

    # ------------------------------------------------------- post writing

    def _post_instruction(self, post: dict) -> str:
        if post.get("is_conversion"):
            return (
                "You just changed your mind and switched sides on this topic. "
                "Write ONE post (max 220 chars) publicly admitting the change "
                "of heart and hinting at what convinced you. Post text only."
            )
        if post.get("reply_to"):
            parent = post.get("parent_text") or ""
            tone = "agree with them enthusiastically" if post.get("agrees") \
                else "push back and argue against their point"
            return (
                f'You are replying to {post["reply_to"]}, who posted: "{parent}".\n'
                f"Write ONE reply (max 200 chars) that starts with {post['reply_to']} "
                f"and makes you {tone}, with an actual argument, not just attitude. "
                "Reply text only."
            )
        return (
            "Write ONE post (max 220 chars) sharing your current take on the "
            "topic. Make it feel personal and specific. Post text only."
        )

    def rewrite_posts(self, sim: Simulation, posts: list[dict]) -> list[dict]:
        """Replace template text with in-character LLM text, concurrently.

        ``posts`` are the dicts returned by ``Simulation.step()``; only the
        first MAX_LLM_POSTS_PER_ROUND non-event posts are rewritten.
        """
        targets = [p for p in posts if not p.get("is_event")][:MAX_LLM_POSTS_PER_ROUND]

        def job(post: dict) -> None:
            persona = sim.population[post["author_id"]]
            text = self._complete(
                self._persona_card(persona, sim.topic),
                self._post_instruction(post),
                max_tokens=500,
            )
            if text:
                post["text"] = text[:280]

        list(self.pool.map(job, targets))
        return posts

    # ------------------------------------------------------------- chat

    def chat(self, persona: Persona, sim: Simulation,
             history: list[dict], message: str) -> Optional[str]:
        """Interview a simulated agent about its opinions."""
        own_posts = [p.text for p in sim.posts if p.author_id == persona.id][-3:]
        own = "\n".join(f"- {t}" for t in own_posts) or "- (you haven't posted yet)"
        system = (
            self._persona_card(persona, sim.topic)
            + f"\nYour own recent posts:\n{own}\n"
            "A curious observer is interviewing you about your views. Answer "
            "in character, conversationally, in 1-3 short sentences. If your "
            "stance moved from where you started, you can explain what you "
            "read that changed your mind. Answer in the same language the "
            "observer uses."
        )
        messages = [
            {"role": m["role"], "content": str(m["content"])[:1000]}
            for m in history[-12:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        messages.append({"role": "user", "content": message})
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=messages,
            )
            if response.stop_reason == "refusal":
                return None
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text.strip() or None
        except Exception:
            return None

    # ------------------------------------------------------------ report

    def report_analysis(self, report: dict) -> Optional[str]:
        """A short analyst's narrative on top of the numeric report."""
        top_posts = "\n".join(
            f'- {p["handle"]} ({p["stance"]}): "{p["text"]}" ({p["likes"]} likes)'
            for p in report.get("top_posts", [])[:5]
        )
        events = "\n".join(
            f'- round {e["round"]}: "{e["headline"]}" (impact {e["impact"]:+.1f})'
            for e in report.get("events", [])
        ) or "- none"
        user = (
            f'Topic: {report["topic"]}\n'
            f'Rounds: {report["rounds"]}, total posts: {report["total_posts"]}\n'
            f'Mean stance: {report["initial"]["mean_opinion"]:+.2f} -> '
            f'{report["final"]["mean_opinion"]:+.2f}, '
            f'polarization {report["final"]["polarization"]:.2f}\n'
            f'Final counts: {report["final"]["counts"]}\n'
            f"Injected events:\n{events}\n"
            f"Most engaging posts:\n{top_posts}"
        )
        return self._complete(
            system=(
                "You are a public-opinion analyst reviewing the results of a "
                "multi-agent social simulation. Write a sharp 3-5 sentence "
                "analysis: what happened, what drove it, and one concrete "
                "prediction or recommendation. No headers, no bullet points."
            ),
            user=user,
            max_tokens=2000,
            effort="medium",
        )
