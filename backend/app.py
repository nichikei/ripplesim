"""RippleSim REST API.

Endpoints
---------
POST /api/simulations              create a simulation
GET  /api/simulations/{id}         current state (metrics + agents)
POST /api/simulations/{id}/step    advance one round, returns that round's posts
POST /api/simulations/{id}/inject  inject a breaking-news event
GET  /api/simulations/{id}/report  final prediction report

Simulations live in memory keyed by a short id — fine for a demo tool,
swap for Redis/DB if it ever needs to scale.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine.report import build_report
from backend.engine.simulation import Simulation
from backend.llm import LlmService
from backend.report_agent import render_markdown

app = FastAPI(title="RippleSim", version="0.2.0")

SIMULATIONS: dict[str, Simulation] = {}
LLM_SIMS: set[str] = set()  # simulations running with LLM-written posts
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

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


def _get_sim(sim_id: str) -> Simulation:
    sim = SIMULATIONS.get(sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    return sim


@app.post("/api/simulations")
def create_simulation(req: CreateSimRequest) -> dict:
    llm_active = bool(req.use_llm and get_llm())

    sim_id = uuid.uuid4().hex[:8]
    SIMULATIONS[sim_id] = Simulation(
        topic=req.topic, n_agents=req.n_agents, seed=req.seed, bias=req.bias
    )
    if llm_active:
        LLM_SIMS.add(sim_id)
    sim = SIMULATIONS[sim_id]
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
    sim = _get_sim(sim_id)
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
    sim = _get_sim(sim_id)
    posts = sim.step()
    if sim_id in LLM_SIMS and (llm := get_llm()):
        posts = llm.rewrite_posts(sim, posts)
    return {
        "round": sim.round,
        "posts": posts,
        "metrics": sim.metrics_history[-1],
        "agents": sim.agents_summary(),
    }


@app.post("/api/simulations/{sim_id}/inject")
def inject_event(sim_id: str, req: InjectEventRequest) -> dict:
    sim = _get_sim(sim_id)
    record = sim.inject_event(req.headline, req.impact, req.reach)
    return {"event": record, "metrics": sim.metrics_history[-1], "agents": sim.agents_summary()}


REPORT_CACHE: dict[str, str] = {}  # sim_id -> markdown (agent runs are expensive)


def _report_markdown(sim_id: str) -> tuple[dict, str, bool]:
    """Build the report and its Markdown rendering. Returns (report, md, by_agent)."""
    sim = _get_sim(sim_id)
    report = build_report(sim)
    if sim_id in REPORT_CACHE:
        return report, REPORT_CACHE[sim_id], True

    written = None
    if sim_id in LLM_SIMS and (llm := get_llm()):
        written = llm.write_report(sim, report)
    markdown = written or render_markdown(report)
    if written:
        REPORT_CACHE[sim_id] = markdown
    return report, markdown, bool(written)


@app.get("/api/simulations/{sim_id}/report")
def get_report(sim_id: str) -> dict:
    report, markdown, by_agent = _report_markdown(sim_id)
    report["markdown"] = markdown
    report["written_by_agent"] = by_agent
    return report


@app.get("/api/simulations/{sim_id}/report.md", response_class=PlainTextResponse)
def download_report(sim_id: str) -> PlainTextResponse:
    """Download the report as a Markdown file."""
    _, markdown, _ = _report_markdown(sim_id)
    slug = "".join(c if c.isalnum() else "-" for c in _get_sim(sim_id).topic).strip("-")[:60]
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ripplesim-{slug or sim_id}.md"'},
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=24)


@app.post("/api/simulations/{sim_id}/agents/{agent_id}/chat")
def chat_with_agent(sim_id: str, agent_id: int, req: ChatRequest) -> dict:
    """Interview a simulated agent (requires the LLM to be available)."""
    sim = _get_sim(sim_id)
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

if FRONTEND_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
