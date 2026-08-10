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

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from backend.engine.personas import Persona
from backend.engine.simulation import Simulation

# Model per job, cheapest that does the job well. Posts are the high-volume
# call (~10 per round) and the simplest task, so they run on Haiku; the
# interview and the report agent need reasoning quality, so they run on Sonnet.
POST_MODEL = "claude-haiku-4-5"
CHAT_MODEL = "claude-sonnet-5"
REPORT_MODEL = "claude-sonnet-5"

# `output_config.effort` is not accepted by these models — sending it is a 400.
MODELS_WITHOUT_EFFORT = ("claude-haiku-4-5", "claude-sonnet-4-5")

MAX_LLM_POSTS_PER_ROUND = 10

logger = logging.getLogger(__name__)


def supports_effort(model: str) -> bool:
    return not model.startswith(MODELS_WITHOUT_EFFORT)

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
        self.post_model = os.environ.get("RIPPLESIM_POST_MODEL", POST_MODEL)
        self.chat_model = os.environ.get("RIPPLESIM_CHAT_MODEL", CHAT_MODEL)
        self.report_model = os.environ.get("RIPPLESIM_REPORT_MODEL", REPORT_MODEL)
        # One worker per post so a round is a single wave of calls, not two —
        # round latency is one API call, not ceil(posts / workers) of them.
        self.pool = ThreadPoolExecutor(max_workers=MAX_LLM_POSTS_PER_ROUND)

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

    def _complete(self, model: str, system: str, user: str,
                  max_tokens: int = 500, effort: str = "low") -> Optional[str]:
        kwargs: dict = {}
        if supports_effort(model):
            kwargs["output_config"] = {"effort": effort}
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                **kwargs,
            )
            if response.stop_reason == "refusal":
                logger.warning("%s refused the request", model)
                return None
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text.strip() or None
        except Exception as exc:
            # Never break the simulation over an API problem — but never hide
            # it either: a revoked key used to look exactly like template mode.
            logger.warning("LLM call to %s failed: %s: %s",
                           model, type(exc).__name__, exc)
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
            "own voice; never mention being an AI or a simulation.\n"
            "Write in the same language the topic is written in — if the topic "
            "is in Vietnamese, post in Vietnamese, and so on."
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

    def rewrite_posts(self, sim: Simulation, posts: list[dict]) -> tuple[list[dict], int]:
        """Replace template text with in-character LLM text, concurrently.

        ``posts`` are the dicts returned by ``Simulation.step()``; only the
        first MAX_LLM_POSTS_PER_ROUND non-event posts are rewritten.

        Returns the posts and how many were actually rewritten, so the caller
        can tell a working LLM from one that is failing every call.
        """
        targets = [p for p in posts if not p.get("is_event")][:MAX_LLM_POSTS_PER_ROUND]

        def job(post: dict) -> bool:
            persona = sim.population[post["author_id"]]
            text = self._complete(
                self.post_model,
                self._persona_card(persona, sim.topic),
                self._post_instruction(post),
                max_tokens=500,
            )
            if not text:
                return False
            text = text[:280]
            post["text"] = text
            # Write back to the simulation's own record too, so the report
            # agent and agent memory see what the feed actually showed rather
            # than the template it replaced.
            stored = sim.post_by_id(post["id"])
            if stored is not None:
                stored.text = text
                stored.llm_written = True
            return True

        written = sum(self.pool.map(job, targets))
        if targets and not written:
            logger.error("Every LLM rewrite failed this round — falling back to templates")
        return posts, written

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
                model=self.chat_model,
                max_tokens=2000,
                # An interview reply is short and conversational; thinking would
                # only add latency to a chat the user is waiting on.
                thinking={"type": "disabled"},
                system=system,
                messages=messages,
            )
            if response.stop_reason == "refusal":
                logger.warning("%s refused the interview request", self.chat_model)
                return None
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text.strip() or None
        except Exception as exc:
            logger.warning("Interview call to %s failed: %s: %s",
                           self.chat_model, type(exc).__name__, exc)
            return None

    # ------------------------------------------------------------ report

    def write_report(self, sim, report: dict) -> Optional[str]:
        """Run the tool-using ReportAgent over a finished simulation."""
        from backend.report_agent import ReportAgent

        return ReportAgent(self.client, self.report_model).write(sim, report)
