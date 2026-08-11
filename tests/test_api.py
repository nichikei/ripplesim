"""API behaviour, with an emphasis on the session store not growing forever."""

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import MAX_SESSIONS, SESSIONS, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_sessions():
    SESSIONS.clear()
    yield
    SESSIONS.clear()


def create(topic: str = "a test topic", **kwargs) -> str:
    res = client.post("/api/simulations", json={"topic": topic, "n_agents": 20, **kwargs})
    assert res.status_code == 200
    return res.json()["id"]


def test_simulation_lifecycle():
    sim_id = create()
    assert client.post(f"/api/simulations/{sim_id}/step").status_code == 200
    assert client.post(f"/api/simulations/{sim_id}/inject",
                       json={"headline": "Something happened", "impact": -0.5}).status_code == 200
    report = client.get(f"/api/simulations/{sim_id}/report")
    assert report.status_code == 200
    assert report.json()["markdown"].startswith("# Opinion report")


def test_unknown_simulation_is_a_404():
    assert client.get("/api/simulations/nope").status_code == 404
    assert client.post("/api/simulations/nope/step").status_code == 404


def test_the_session_store_is_capped():
    for i in range(MAX_SESSIONS + 12):
        create(f"topic number {i}")
    assert len(SESSIONS) == MAX_SESSIONS


def test_eviction_drops_the_least_recently_used_session():
    first = create("the first topic")
    second = create("the second topic")

    # Keep using `first` so `second` becomes the coldest session.
    for _ in range(MAX_SESSIONS):
        client.get(f"/api/simulations/{first}")
        create("filler topic")

    assert first in SESSIONS
    assert second not in SESSIONS
    assert client.get(f"/api/simulations/{second}").status_code == 404


def test_evicting_a_session_releases_everything_it_owned():
    """The whole point of one Session object: no half-freed leftovers."""
    sim_id = create("a topic worth caching")
    SESSIONS[sim_id].report_markdown = "# cached report"
    SESSIONS[sim_id].llm = True

    for i in range(MAX_SESSIONS + 1):
        create(f"filler {i}")

    assert sim_id not in SESSIONS
    # Nothing else in the module still references the evicted id.
    assert not any(
        isinstance(value, (dict, set)) and sim_id in value
        for name, value in vars(app_module).items()
        if not name.startswith("__")
    )


def test_report_is_only_generated_once_per_session():
    sim_id = create()
    client.post(f"/api/simulations/{sim_id}/step")
    SESSIONS[sim_id].report_markdown = "# a cached agent report"

    body = client.get(f"/api/simulations/{sim_id}/report").json()
    assert body["markdown"] == "# a cached agent report"
    assert body["written_by_agent"] is True


def test_report_downloads_with_a_filename_from_the_topic():
    sim_id = create("Free transport for students")
    res = client.get(f"/api/simulations/{sim_id}/report.md")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    assert "Free-transport-for-students" in res.headers["content-disposition"]


def test_a_non_ascii_topic_does_not_break_the_download_header():
    """HTTP headers are latin-1; a Vietnamese topic used to 500 the download."""
    sim_id = create("Hà Nội cấm xe máy xăng trong vành đai 1")
    res = client.get(f"/api/simulations/{sim_id}/report.md")
    assert res.status_code == 200
    disposition = res.headers["content-disposition"]
    disposition.encode("latin-1")           # the header itself must be sendable
    assert "filename*=UTF-8''" in disposition  # original name preserved for modern clients


def test_capabilities_reports_llm_state():
    body = client.get("/api/capabilities").json()
    assert set(body) == {"llm_available", "models"}
    assert isinstance(body["llm_available"], bool)
