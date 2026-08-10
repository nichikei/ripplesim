# 🌊 RippleSim

**Drop a piece of news into a virtual society — watch the ripples of public opinion spread.**

RippleSim is a multi-agent social simulation engine. Given a seed event (a news headline,
a policy draft, a product launch), it generates a population of agents with distinct
personalities, connects them in a realistic scale-free social network, and simulates how
opinions form, spread, and polarize round by round. You can inject breaking news
mid-simulation ("god mode") and watch the society react, then read a generated
prediction report: verdict, opinion trajectory, top influencers, most viral posts.

Inspired by large multi-agent prediction engines like MiroFish, but built from scratch
with a deliberately small, readable core — no simulation framework, no chart library.

## ✨ Features

- **Persona generator** — 8 archetypes (journalist, skeptic, enthusiast, troll, ...) with
  per-agent opinion, conviction, sociability and expressiveness
- **Scale-free social network** — Barabási–Albert preferential attachment, implemented
  by hand (~40 lines), so a few hub "influencers" emerge naturally
- **Opinion dynamics** — bounded-confidence model with a backfire effect: content too far
  from an agent's views pushes it *away*; broadcast news uses a separate shock model
- **Viral spread** — emotional posts travel 2 hops instead of 1; likes/shares feed an
  engagement-based influencer ranking
- **God mode** — inject a breaking-news event mid-run with chosen impact and reach
- **Prediction report** — verdict (FAVORABLE / HOSTILE / DIVIDED / CONTESTED), trend,
  stance distribution, top influencers, most viral post
- **Live dashboard** — real-time feed, hand-rolled canvas charts (opinion trajectory,
  stance distribution, population map), zero front-end dependencies
- **Optional LLM mode** — agents write unique posts via the Anthropic API; falls back to
  stance-based templates offline
- **Reproducible** — pass a `seed` for deterministic runs; 11 unit tests on the engine

## 🚀 Quickstart

```bash
pip install -r requirements.txt
uvicorn backend.app:app --port 8123
# open http://localhost:8123
```

Optional LLM-generated posts:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# then tick "use_llm" via the API (POST /api/simulations {"use_llm": true, ...})
```

Run tests:

```bash
python -m pytest tests/ -q
```

## 🏗 Architecture

```
frontend/  (vanilla JS + hand-rolled canvas charts)
   │  fetch /api/*
   ▼
backend/app.py          FastAPI — simulation lifecycle endpoints
backend/llm.py          optional Anthropic-powered post writer
backend/engine/
   personas.py          archetype-based population generator
   network.py           Barabási–Albert scale-free graph
   opinion.py           bounded confidence + backfire + news shock
   content.py           stance-based post templates, virality scoring
   simulation.py        round loop, viral spread, event injection
   report.py            verdict, trend, influencer ranking
```

**Simulation round:** agents wake up by sociability → each writes a post → virality
decides reach (1–2 hops) → readers update opinions via bounded confidence → likes and
shares accrue to the author → population metrics recorded.

## 📡 API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/simulations` | Create a simulation (`topic`, `n_agents`, `bias`, `seed`, `use_llm`) |
| GET  | `/api/simulations/{id}` | Current state, metrics history, agents |
| POST | `/api/simulations/{id}/step` | Advance one round; returns that round's posts |
| POST | `/api/simulations/{id}/inject` | Inject a breaking-news event (`headline`, `impact`, `reach`) |
| GET  | `/api/simulations/{id}/report` | Final prediction report |

## 🔬 Model notes

- **Bounded confidence** (Deffuant-style): an agent only moves toward opinions within
  its openness window (wider for low-conviction agents). Content far outside the window
  triggers a small *backfire* — mirroring how contrarian content hardens beliefs.
- **News shock**: broadcast events bypass bounded confidence — an extreme headline
  shifts everyone toward its implication instead of backfiring. (Found via a failing
  unit test: an impact −1.0 event originally moved mean opinion *up*.)
- **Polarization** is measured as the population standard deviation of opinions; the
  verdict flags a society as DIVIDED when it exceeds 0.55.

## 🗺 Roadmap

- [ ] Network visualization (force-directed graph)
- [ ] Chat with an individual agent about why it changed its mind
- [ ] Multiple competing topics in one society
- [ ] Export report as PDF
