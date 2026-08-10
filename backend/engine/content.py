"""Post content generation.

Default mode is template-based (fast, free, deterministic under a seed):
each stance bucket has a pool of post templates with a ``{topic}`` slot.
An optional LLM generator can be plugged in via ``set_llm_writer`` — the
simulation stays agnostic about where text comes from.
"""

from __future__ import annotations

import random
from typing import Callable, Optional

from .personas import Persona

TEMPLATES: dict[str, list[str]] = {
    "strong_support": [
        "This is huge. {topic} is exactly what we needed. 🔥",
        "Been saying this for years — {topic} changes everything. All in.",
        "Massive W. {topic} is the best news I've seen all month. 🚀",
        "If you're still doubting {topic}, you're not paying attention.",
    ],
    "support": [
        "Cautiously optimistic about {topic}. The upside looks real.",
        "Read the details on {topic} — honestly, more good than bad here.",
        "{topic} seems like a step in the right direction. 👍",
        "Not perfect, but {topic} deserves more credit than it's getting.",
    ],
    "neutral": [
        "Interesting development: {topic}. Curious where this goes.",
        "Anyone have a good breakdown of {topic}? Hard to judge yet.",
        "Watching the {topic} story unfold. Too early to call.",
        "Lots of noise about {topic} today. Waiting for actual data.",
    ],
    "oppose": [
        "Not convinced by {topic}. The numbers don't add up for me.",
        "Everyone's hyping {topic} but nobody's asking who pays for it.",
        "{topic} sounds nice on paper. In practice? Doubt it. 🤨",
        "We've seen things like {topic} before. It rarely ends well.",
    ],
    "strong_oppose": [
        "Hard no on {topic}. This is a disaster waiting to happen.",
        "{topic} is being sold with smoke and mirrors. Wake up, people. 🚨",
        "Can't believe anyone falls for {topic}. Absolute train wreck.",
        "Bookmark this: {topic} will blow up in everyone's face.",
    ],
}

# Optional pluggable LLM writer: (persona, topic, stance) -> post text
LlmWriter = Callable[[Persona, str, str], Optional[str]]
_llm_writer: Optional[LlmWriter] = None


def set_llm_writer(writer: Optional[LlmWriter]) -> None:
    global _llm_writer
    _llm_writer = writer


def write_post(persona: Persona, topic: str, rng: random.Random) -> str:
    """Generate the text of one post for ``persona`` about ``topic``."""
    stance = persona.stance
    if _llm_writer is not None:
        text = _llm_writer(persona, topic, stance)
        if text:
            return text
    return rng.choice(TEMPLATES[stance]).format(topic=topic)


def virality_score(persona: Persona, rng: random.Random) -> float:
    """How likely a post is to be liked/shared (0..1).

    Emotional posts travel further — expressiveness dominates, with noise.
    """
    extremity = abs(persona.opinion)  # extreme takes get more engagement
    score = 0.5 * persona.expressiveness + 0.3 * extremity + 0.2 * rng.random()
    return min(1.0, score)
