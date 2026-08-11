"""RippleSim REST API.

Endpoints
---------
POST /api/simulations              create a simulation
GET  /api/simulations/{id}         current state (metrics + agents)
POST /api/simulations/{id}/step    advance one round, returns that round's posts
POST /api/simulations/{id}/inject  inject a breaking-news event
GET  /api/simulations/{id}/report  final prediction report

Sessions live in memory keyed by a short id — fine for a demo tool, swap for
Redis/DB if it ever needs to scale. The store is capped and evicts
least-recently-used sessions so a long-running server cannot grow forever.
"""

from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine.report import build_report
from backend.engine.simulation import Simulation
from backend.llm import LlmService
from backend.report_agent import render_markdown

app = FastAPI(title="RippleSim", version="0.2.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

MAX_SESSIONS = 50


@dataclass
class Session:
    """Everything one simulation owns, so eviction is a single operation.

    Keeping the simulation, its LLM flag and its cached report together makes
    it impossible to drop one and leak the others.
    """

    sim: Simulation
    llm: bool = False
    report_markdown: str | None = None


# Ordered by least-recently-used first.
SESSIONS: OrderedDict[str, Session] = OrderedDict()


def _touch(sim_id: str) -> Session:
    """Fetch a session and mark it as most recently used."""
    session = SESSIONS.get(sim_id)
    if session is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    SESSIONS.move_to_end(sim_id)
    return session


def _evict_oldest() -> None:
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)

_llm: LlmService | None = None
_llm_checked = False


def get_llm() -> LlmService | None:
    """Lazily build the shared LLM service (None when unavailable)."""
    global _llm, _llm_checked
    if not _llm_checked:
        _llm = LlmService.create()
        _llm_checked = True
    return _llm


class CreateSimRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    n_agents: int = Field(default=100, ge=10, le=1000)
    bias: float = Field(default=0.0, ge=-1.0, le=1.0,
                        description="How favourable the seed event is (-1..1)")
    seed: int | None = Field(default=None, description="RNG seed for reproducible runs")
    use_llm: bool = Field(default=False,
                          description="Generate post text with an LLM (needs ANTHROPIC_API_KEY)")


class InjectEventRequest(BaseModel):
    headline: str = Field(min_length=3, max_length=200)
    impact: float = Field(ge=-1.0, le=1.0)
    reach: float = Field(default=0.6, ge=0.05, le=1.0)


@app.get("/api/capabilities")
def capabilities() -> dict:
    """What this server can do, so the UI can configure itself on load."""
    llm = get_llm()
    return {
        "llm_available": llm is not None,
        "models": {
            "posts": llm.post_model if llm else None,
            "chat": llm.chat_model if llm else None,
            "report": llm.report_model if llm else None,
        },
    }


@app.post("/api/simulations")
def create_simulation(req: CreateSimRequest) -> dict:
    llm_active = bool(req.use_llm and get_llm())

    sim_id = uuid.uuid4().hex[:8]
    sim = Simulation(
        topic=req.topic, n_agents=req.n_agents, seed=req.seed, bias=req.bias
    )
    SESSIONS[sim_id] = Session(sim=sim, llm=llm_active)
    _evict_oldest()
    return {
        "id": sim_id,
        "topic": sim.topic,
        "n_agents": sim.n_agents,
        "llm_active": llm_active,
        "metrics": sim.metrics_history[-1],
        "agents": sim.agents_summary(),
    }


@app.get("/api/simulations/{sim_id}")
def get_simulation(sim_id: str) -> dict:
    sim = _touch(sim_id).sim
    return {
        "id": sim_id,
        "topic": sim.topic,
        "round": sim.round,
        "metrics": sim.metrics_history[-1],
        "history": sim.metrics_history,
        "agents": sim.agents_summary(),
        "events": sim.events,
    }


@app.post("/api/simulations/{sim_id}/step")
def step_simulation(sim_id: str) -> dict:
    session = _touch(sim_id)
    sim = session.sim
    posts = sim.step()
    llm_written: int | None = None
    if session.llm and (llm := get_llm()):
        posts, llm_written = llm.rewrite_posts(sim, posts)
    return {
        # How many posts the LLM actually wrote this round. 0 while in LLM
        # mode means every call failed — the UI says so instead of silently
        # showing templates.
        "llm_written": llm_written,
        "round": sim.round,
        "posts": posts,
        "metrics": sim.metrics_history[-1],
        "agents": sim.agents_summary(),
    }


@app.post("/api/simulations/{sim_id}/inject")
def inject_event(sim_id: str, req: InjectEventRequest) -> dict:
    sim = _touch(sim_id).sim
    record = sim.inject_event(req.headline, req.impact, req.reach)
    return {"event": record, "metrics": sim.metrics_history[-1], "agents": sim.agents_summary()}


def _report_markdown(sim_id: str) -> tuple[dict, str, bool]:
    """Build the report and its Markdown rendering. Returns (report, md, by_agent).

    An agent run is slow and costs money, so its output is cached on the
    session and reused for the download endpoint.
    """
    session = _touch(sim_id)
    report = build_report(session.sim)
    if session.report_markdown is not None:
        return report, session.report_markdown, True

    written = None
    if session.llm and (llm := get_llm()):
        written = llm.write_report(session.sim, report)
    if written:
        session.report_markdown = written
        return report, written, True
    return report, render_markdown(report), False


@app.get("/api/simulations/{sim_id}/report")
def get_report(sim_id: str) -> dict:
    report, markdown, by_agent = _report_markdown(sim_id)
    report["markdown"] = markdown
    report["written_by_agent"] = by_agent
    return report


def content_disposition(topic: str, fallback: str) -> str:
    """Build a Content-Disposition header that survives non-ASCII topics.

    HTTP headers are latin-1, but `str.isalnum()` is true for 'ộ' — so a
    Vietnamese topic used to crash the download with a UnicodeEncodeError.
    RFC 5987 solves it properly: an ASCII filename for old clients plus a
    UTF-8 one that keeps the original characters.
    """
    ascii_slug = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9]", "-", topic)).strip("-")[:60]
    utf8_name = quote(f"ripplesim-{topic[:60]}.md", safe="")
    return (f'attachment; filename="ripplesim-{ascii_slug or fallback}.md"; '
            f"filename*=UTF-8''{utf8_name}")


@app.get("/api/simulations/{sim_id}/report.md", response_class=PlainTextResponse)
def download_report(sim_id: str) -> PlainTextResponse:
    """Download the report as a Markdown file."""
    _, markdown, _ = _report_markdown(sim_id)
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition(SESSIONS[sim_id].sim.topic, sim_id)},
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=24)


@app.post("/api/simulations/{sim_id}/agents/{agent_id}/chat")
def chat_with_agent(sim_id: str, agent_id: int, req: ChatRequest) -> dict:
    """Interview a simulated agent (requires the LLM to be available)."""
    sim = _touch(sim_id).sim
    if not 0 <= agent_id < len(sim.population):
        raise HTTPException(status_code=404, detail="agent not found")
    llm = get_llm()
    if llm is None:
        raise HTTPException(status_code=503,
                            detail="LLM unavailable — set ANTHROPIC_API_KEY on the server")
    persona = sim.population[agent_id]
    reply = llm.chat(persona, sim, req.history, req.message)
    if reply is None:
        raise HTTPException(status_code=502, detail="LLM request failed")
    return {
        "reply": reply,
        "agent": {"id": persona.id, "name": persona.name, "handle": persona.handle,
                  "avatar": persona.avatar, "archetype": persona.archetype,
                  "opinion": round(persona.opinion, 3)},
    }


# --- static frontend -------------------------------------------------------

class NoCacheStaticFiles(StaticFiles):
    """Serve the frontend with revalidation forced.

    Without this the browser keeps serving a cached app.js after a deploy, so
    users silently run old code against a new API.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


if FRONTEND_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR), name="frontend")
