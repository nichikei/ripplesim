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

REPLY_AGREE = [
    "{handle} Exactly this. Couldn't have said it better.",
    "{handle} 100%. More people need to see this take on {topic}.",
    "{handle} This. All of this. 👏",
    "{handle} Finally someone says it out loud.",
]

REPLY_DISAGREE = [
    "{handle} Respectfully, that's not how {topic} works at all.",
    "{handle} Wild take. Did you actually read anything about {topic}?",
    "{handle} Hard disagree. The facts on {topic} say otherwise.",
    "{handle} You're missing the whole point of {topic}, honestly.",
]

CONVERSION = {
    "to_support": [
        "Okay, I've been reading the threads on {topic}... I was wrong. I'm coming around.",
        "Didn't expect to say this, but the arguments for {topic} are winning me over.",
        "Update: after seeing what people are saying, I'm warming up to {topic}.",
    ],
    "to_oppose": [
        "I defended {topic} at first. After what I've seen today, I can't anymore.",
        "Changed my mind on {topic}. The critics are making too much sense.",
        "Update: the more I read about {topic}, the worse it looks. I'm out.",
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


def write_reply(topic: str, target_handle: str, agree: bool, rng: random.Random) -> str:
    """A short reply to another agent's post."""
    pool = REPLY_AGREE if agree else REPLY_DISAGREE
    return rng.choice(pool).format(handle=target_handle, topic=topic)


def write_conversion(topic: str, now_supports: bool, rng: random.Random) -> str:
    """Posted when an agent flips sides — makes the inner opinion shift visible."""
    key = "to_support" if now_supports else "to_oppose"
    return rng.choice(CONVERSION[key]).format(topic=topic)


def virality_score(persona: Persona, rng: random.Random) -> float:
    """How likely a post is to be liked/shared (0..1).

    Emotional posts travel further — expressiveness dominates, with noise.
    """
    extremity = abs(persona.opinion)  # extreme takes get more engagement
    score = 0.5 * persona.expressiveness + 0.3 * extremity + 0.2 * rng.random()
    return min(1.0, score)
