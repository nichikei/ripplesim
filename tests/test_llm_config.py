"""The LLM layer must degrade safely and must not send parameters a model rejects."""

import unicodedata

import backend.llm as llm


def test_effort_is_withheld_from_models_that_reject_it():
    # Sending output_config.effort to these is a 400.
    assert not llm.supports_effort("claude-haiku-4-5")
    assert not llm.supports_effort("claude-sonnet-4-5")
    # Sonnet 5 and the Opus line accept it.
    assert llm.supports_effort("claude-sonnet-5")
    assert llm.supports_effort("claude-opus-5")


def test_default_models_are_the_cheap_split():
    assert llm.POST_MODEL == "claude-haiku-4-5"
    assert llm.CHAT_MODEL == llm.REPORT_MODEL == "claude-sonnet-5"
    # The post model is the one we call ~10x per round, so it must be a model
    # we deliberately keep cheap.
    assert not llm.supports_effort(llm.POST_MODEL)


def test_decomposed_vietnamese_is_composed():
    """Model output can arrive decomposed; 'tắt' must not render as 'tă´t'."""
    decomposed = "Tóm tắt"          # Tóm tắt, fully decomposed
    assert llm.normalize_text(decomposed) == "Tóm tắt"
    assert len(llm.normalize_text(decomposed)) < len(decomposed)


def test_normalizing_leaves_composed_text_alone():
    assert llm.normalize_text("Tóm tắt") == "Tóm tắt"
    assert llm.normalize_text("plain ascii") == "plain ascii"


def test_service_is_absent_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "ENV_FILE", tmp_path / "missing.env")
    assert llm.LlmService.create() is None


def test_env_file_does_not_override_a_real_environment_variable(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr(llm, "ENV_FILE", env)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-environment")
    llm.load_env_file()
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "from-environment"


def test_env_file_supplies_the_key_when_the_environment_has_none(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nANTHROPIC_API_KEY="quoted-key"\n\n', encoding="utf-8")
    monkeypatch.setattr(llm, "ENV_FILE", env)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm.load_env_file()
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "quoted-key"
