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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine import content
from backend.engine.report import build_report
from backend.engine.simulation import Simulation
from backend.llm import make_llm_writer

app = FastAPI(title="RippleSim", version="0.1.0")

SIMULATIONS: dict[str, Simulation] = {}
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


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
    llm_active = False
    if req.use_llm:
        writer = make_llm_writer()
        content.set_llm_writer(writer)
        llm_active = writer is not None
    else:
        content.set_llm_writer(None)

    sim_id = uuid.uuid4().hex[:8]
    SIMULATIONS[sim_id] = Simulation(
        topic=req.topic, n_agents=req.n_agents, seed=req.seed, bias=req.bias
    )
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


@app.get("/api/simulations/{sim_id}/report")
def get_report(sim_id: str) -> dict:
    return build_report(_get_sim(sim_id))


# --- static frontend -------------------------------------------------------

if FRONTEND_DIR.is_dir():
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
