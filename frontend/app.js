/* RippleSim dashboard logic: create a simulation, step it round by round,
   render the live feed and metrics. */

const $ = (id) => document.getElementById(id);

const state = {
  simId: null,
  running: false,
  totalRounds: 12,
};

/* ---- slider labels ---- */
for (const [slider, label] of [
  ["n-agents", "n-agents-value"],
  ["bias", "bias-value"],
  ["rounds", "rounds-value"],
  ["event-impact", "event-impact-value"],
]) {
  $(slider).addEventListener("input", () => ($(label).textContent = $(slider).value));
}

/* ---- API helpers ---- */
async function api(path, method = "GET", body = null) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---- rendering ---- */
function renderMetrics(metrics, round) {
  $("stat-round").textContent = `${round}/${state.totalRounds}`;
  const mean = metrics.mean_opinion;
  $("stat-mean").textContent = (mean > 0 ? "+" : "") + mean.toFixed(2);
  $("stat-mean").style.color =
    mean >= 0.15 ? "var(--support)" : mean <= -0.15 ? "var(--oppose)" : "var(--ink)";
  $("stat-support").textContent = metrics.counts.support;
  $("stat-oppose").textContent = metrics.counts.oppose;
}

function renderPosts(posts) {
  const feed = $("feed");
  for (const post of posts.slice(0, 8)) {
    const div = document.createElement("div");
    div.className = `post ${post.stance}`;
    div.innerHTML = `
      <div class="post-head">
        <span>${post.avatar}</span>
        <span class="post-name">${esc(post.author)}</span>
        <span class="post-handle">${esc(post.handle)} · ${esc(post.archetype)}</span>
        <span class="post-round">R${post.round}</span>
      </div>
      <div class="post-text">${esc(post.text)}</div>
      <div class="post-meta">❤️ ${post.likes} · 🔁 ${post.shares}</div>`;
    feed.prepend(div);
  }
  // Trim old posts, but never drop pinned breaking-news event cards.
  while (feed.children.length > 60) {
    let victim = feed.lastElementChild;
    while (victim && victim.classList.contains("event")) victim = victim.previousElementSibling;
    if (!victim) break;
    feed.removeChild(victim);
  }
}

function esc(s) {
  const div = document.createElement("div");
  div.textContent = String(s);
  return div.innerHTML;
}

/* ---- main flow ---- */
async function runSimulation() {
  if (state.running) return;
  state.running = true;
  $("run-btn").disabled = true;
  $("inject-btn").disabled = false;
  $("feed").innerHTML = "";
  state.totalRounds = Number($("rounds").value);

  try {
    const sim = await api("/simulations", "POST", {
      topic: $("topic").value.trim(),
      n_agents: Number($("n-agents").value),
      bias: Number($("bias").value),
    });
    state.simId = sim.id;
    renderMetrics(sim.metrics, 0);
    onSimCreated(sim);

    for (let round = 1; round <= state.totalRounds; round++) {
      $("feed-status").textContent = `— round ${round}/${state.totalRounds}`;
      const step = await api(`/simulations/${state.simId}/step`, "POST");
      renderPosts(step.posts);
      renderMetrics(step.metrics, step.round);
      onStep(step);
      await sleep(650);
    }
    $("feed-status").textContent = "— finished";
    await onFinished();
  } catch (err) {
    $("feed-status").textContent = `— error: ${err.message}`;
  } finally {
    state.running = false;
    $("run-btn").disabled = false;
    $("inject-btn").disabled = true;
  }
}

async function injectEvent() {
  if (!state.simId || !state.running) return;
  const headline = $("event-headline").value.trim();
  if (!headline) return;
  const res = await api(`/simulations/${state.simId}/inject`, "POST", {
    headline,
    impact: Number($("event-impact").value),
  });
  renderPosts([
    {
      round: res.event.round, author: "Newswire", handle: "@breaking", avatar: "🗞️",
      archetype: "event", text: `BREAKING: ${headline}`, stance: "event",
      likes: res.event.reached, shares: 0,
    },
  ]);
  onInject(res);
}

/* Extension hooks — implemented by charts.js (kept as no-ops until then). */
let onSimCreated = () => {};
let onStep = () => {};
let onInject = () => {};
let onFinished = async () => {};

$("run-btn").addEventListener("click", runSimulation);
$("inject-btn").addEventListener("click", injectEvent);
