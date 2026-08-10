"""Optional LLM-powered post generation via the Anthropic API.

Entirely optional: without the `anthropic` package or an ANTHROPIC_API_KEY,
the simulation silently falls back to template posts. With them, agents write
unique posts in character.

    export ANTHROPIC_API_KEY=sk-ant-...
    export RIPPLESIM_MODEL=claude-opus-5   # optional override
"""

from __future__ import annotations

import os
from typing import Optional

from backend.engine.personas import Persona

DEFAULT_MODEL = "claude-opus-5"

STANCE_HINT = {
    "strong_support": "strongly supports it and is excited",
    "support": "cautiously supports it",
    "neutral": "is undecided and curious",
    "oppose": "is skeptical of it",
    "strong_oppose": "strongly opposes it and is upset",
}


def make_llm_writer():
    """Return an LlmWriter callable, or None if the LLM is unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    model = os.environ.get("RIPPLESIM_MODEL", DEFAULT_MODEL)

    def write(persona: Persona, topic: str, stance: str) -> Optional[str]:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                output_config={"effort": "low"},
                system=(
                    "You write single social-media posts for simulated users. "
                    "Reply with the post text only — no quotes, no explanation. "
                    "Max 200 characters."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"User: {persona.name}, archetype '{persona.archetype}', "
                            f"who {STANCE_HINT[stance]}.\n"
                            f"Topic: {topic}\n"
                            "Write their post."
                        ),
                    }
                ],
            )
            if response.stop_reason == "refusal":
                return None
            text = next((b.text for b in response.content if b.type == "text"), "")
            return text.strip()[:280] or None
        except Exception:
            return None  # any API failure -> template fallback

    return write
