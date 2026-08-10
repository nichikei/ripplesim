/* Hand-rolled canvas charts — no chart library.
   Colors follow the dashboard palette: blue = mean stance / support pole,
   orange = polarization, red = oppose pole, gray = neutral midpoint. */

const COLORS = {
  blue: "#2a78d6",
  orange: "#eb6834",
  red: "#e34948",
  gray: "#8b857a",
  midGray: "#ddd8ca",
  grid: "#e7e3d8",
  ink2: "#57534a",
};

let history = [];   // metrics per round
let eventRounds = [];
let agents = [];
let mapLayout = null; // {cols, cell} of the population grid, for hover hit-testing

const TRAJ_PAD = { l: 30, r: 8, t: 8, b: 18 };

/* ---------- opinion trajectory (2 series, one -1..1 axis) ---------- */
function drawTrajectory() {
  const canvas = document.getElementById("chart-trajectory");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const pad = TRAJ_PAD;
  ctx.clearRect(0, 0, W, H);

  const x = (i) =>
    pad.l + (history.length < 2 ? 0 : (i / (history.length - 1)) * (W - pad.l - pad.r));
  const y = (v) => pad.t + ((1 - v) / 2) * (H - pad.t - pad.b); // v in [-1, 1]

  // grid + axis labels
  ctx.strokeStyle = COLORS.grid;
  ctx.fillStyle = COLORS.gray;
  ctx.font = "10px system-ui";
  ctx.lineWidth = 1;
  for (const v of [-1, -0.5, 0, 0.5, 1]) {
    ctx.beginPath();
    ctx.moveTo(pad.l, y(v));
    ctx.lineTo(W - pad.r, y(v));
    ctx.stroke();
    ctx.fillText(v > 0 ? `+${v}` : `${v}`, 4, y(v) + 3);
  }

  // event markers
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = COLORS.orange;
  for (const r of eventRounds) {
    ctx.beginPath();
    ctx.moveTo(x(r), pad.t);
    ctx.lineTo(x(r), H - pad.b);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  const line = (key, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    history.forEach((m, i) => (i === 0 ? ctx.moveTo(x(i), y(m[key])) : ctx.lineTo(x(i), y(m[key]))));
    ctx.stroke();
    // direct label: current value at the line's end
    const last = history[history.length - 1];
    ctx.fillStyle = COLORS.ink2;
    ctx.fillText(last[key].toFixed(2), Math.min(x(history.length - 1) + 3, W - 28), y(last[key]) - 4);
  };
  if (history.length) {
    line("mean_opinion", COLORS.blue);
    line("polarization", COLORS.orange);
  }
}

/* ---------- stance distribution (diverging stacked bar) ---------- */
function drawDistribution() {
  if (!history.length) return;
  const { support, neutral, oppose } = history[history.length - 1].counts;
  const total = support + neutral + oppose || 1;
  const bar = document.getElementById("dist-bar");
  bar.innerHTML = "";
  for (const [count, color] of [
    [support, COLORS.blue],
    [neutral, COLORS.midGray],
    [oppose, COLORS.red],
  ]) {
    const seg = document.createElement("div");
    seg.style.flexGrow = String(count);
    seg.style.background = color;
    bar.appendChild(seg);
  }
  document.getElementById("dist-labels").innerHTML =
    `<span>support <b>${support}</b> (${Math.round((100 * support) / total)}%)</span>` +
    `<span>neutral <b>${neutral}</b></span>` +
    `<span>oppose <b>${oppose}</b> (${Math.round((100 * oppose) / total)}%)</span>`;
}

/* ---------- population map (diverging color per agent) ---------- */
function lerp(a, b, t) {
  return Math.round(a + (b - a) * t);
}
function divergingColor(opinion) {
  // neutral midpoint -> blue (support) or red (oppose)
  const mid = [0xdd, 0xd8, 0xca];
  const pole = opinion >= 0 ? [0x2a, 0x78, 0xd6] : [0xe3, 0x49, 0x48];
  const t = Math.min(1, Math.abs(opinion));
  return `rgb(${lerp(mid[0], pole[0], t)},${lerp(mid[1], pole[1], t)},${lerp(mid[2], pole[2], t)})`;
}

function drawAgentGrid() {
  const canvas = document.getElementById("agent-grid");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!agents.length) return;

  const cols = Math.ceil(Math.sqrt(agents.length * (canvas.width / canvas.height)));
  const rows = Math.ceil(agents.length / cols);
  const cell = Math.min(canvas.width / cols, canvas.height / rows);
  const size = Math.max(2, cell - 2); // 2px surface gap between fills
  mapLayout = { cols, cell };

  agents.forEach((agent, i) => {
    const cx = (i % cols) * cell;
    const cy = Math.floor(i / cols) * cell;
    ctx.fillStyle = divergingColor(agent.opinion);
    ctx.beginPath();
    ctx.roundRect(cx, cy, size, size, 2);
    ctx.fill();
  });
}

/* ---------- report ---------- */
async function renderReport() {
  const report = await api(`/simulations/${state.simId}/report`);
  document.getElementById("report-card").classList.remove("hidden");
  const el = document.getElementById("report");
  el.innerHTML = `
    <div class="verdict">${esc(report.verdict)}</div>
    <div class="summary">${esc(report.summary)}</div>
    <h3>Top influencers</h3>
    ${report.top_influencers
      .map(
        (p) => `<div class="influencer"><span>${p.avatar}</span><b>${esc(p.name)}</b>
                <span>${esc(p.handle)}</span><span>🔥 ${p.engagement}</span></div>`
      )
      .join("")}
    <h3>Most viral post</h3>
    <div class="summary">${report.top_posts[0] ? `“${esc(report.top_posts[0].text)}” — ${esc(report.top_posts[0].handle)}, ❤️ ${report.top_posts[0].likes}` : "–"}</div>
    ${report.ai_analysis ? `<h3>🧠 AI analyst</h3><div class="summary ai-analysis">${esc(report.ai_analysis)}</div>` : ""}`;
}

/* ---------- hover tooltips ---------- */
function setupTooltips() {
  const traj = document.getElementById("chart-trajectory");
  const trajTip = document.getElementById("chart-tooltip");
  traj.addEventListener("mousemove", (e) => {
    if (history.length < 2) return;
    const rect = traj.getBoundingClientRect();
    const x = ((e.clientX - rect.left) * traj.width) / rect.width;
    const t = (x - TRAJ_PAD.l) / (traj.width - TRAJ_PAD.l - TRAJ_PAD.r);
    const i = Math.round(t * (history.length - 1));
    if (i < 0 || i >= history.length) return trajTip.classList.add("hidden");
    const m = history[i];
    const evt = eventRounds.includes(m.round) ? " · ⚡ event" : "";
    trajTip.innerHTML =
      `<b>Round ${m.round}</b>${evt}<br>` +
      `mean ${m.mean_opinion >= 0 ? "+" : ""}${m.mean_opinion.toFixed(2)} · ` +
      `polarization ${m.polarization.toFixed(2)}`;
    trajTip.style.left = `${e.clientX - rect.left}px`;
    trajTip.style.top = `${e.clientY - rect.top}px`;
    trajTip.classList.remove("hidden");
  });
  traj.addEventListener("mouseleave", () => trajTip.classList.add("hidden"));

  const map = document.getElementById("agent-grid");
  const mapTip = document.getElementById("map-tooltip");
  map.addEventListener("mousemove", (e) => {
    if (!mapLayout || !agents.length) return;
    const rect = map.getBoundingClientRect();
    const x = ((e.clientX - rect.left) * map.width) / rect.width;
    const y = ((e.clientY - rect.top) * map.height) / rect.height;
    const idx = Math.floor(y / mapLayout.cell) * mapLayout.cols + Math.floor(x / mapLayout.cell);
    const agent = agents[idx];
    if (!agent) return mapTip.classList.add("hidden");
    mapTip.innerHTML =
      `${agent.avatar} <b>${agent.name}</b> ${agent.handle}<br>` +
      `${agent.archetype} · stance ${agent.opinion >= 0 ? "+" : ""}${agent.opinion.toFixed(2)} · ` +
      `${agent.followers} followers`;
    mapTip.style.left = `${e.clientX - rect.left}px`;
    mapTip.style.top = `${e.clientY - rect.top}px`;
    mapTip.classList.remove("hidden");
  });
  map.addEventListener("mouseleave", () => mapTip.classList.add("hidden"));
  map.style.cursor = "pointer";
  map.addEventListener("click", (e) => {
    if (!mapLayout || !agents.length) return;
    const rect = map.getBoundingClientRect();
    const x = ((e.clientX - rect.left) * map.width) / rect.width;
    const y = ((e.clientY - rect.top) * map.height) / rect.height;
    const idx = Math.floor(y / mapLayout.cell) * mapLayout.cols + Math.floor(x / mapLayout.cell);
    if (agents[idx]) openChat(agents[idx]);
  });
}
setupTooltips();

/* ---------- wire into app.js hooks ---------- */
onSimCreated = (sim) => {
  history = [sim.metrics];
  eventRounds = [];
  agents = sim.agents;
  document.getElementById("report-card").classList.add("hidden");
  drawTrajectory();
  drawDistribution();
  drawAgentGrid();
};

onStep = (step) => {
  history.push(step.metrics);
  agents = step.agents;
  drawTrajectory();
  drawDistribution();
  drawAgentGrid();
};

onInject = (res) => {
  eventRounds.push(res.event.round);
  agents = res.agents;
  drawTrajectory();
  drawAgentGrid();
};

onFinished = async () => {
  await renderReport();
};
