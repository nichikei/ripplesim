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
]) {
  $(slider).addEventListener("input", () => ($(label).textContent = $(slider).value));
}

/* ---- status helpers ---- */
function setStatus(mode, text) {
  const pill = $("status-pill");
  pill.className = `pill pill-${mode}`;
  pill.textContent = text;
}

function setProgress(round, total) {
  $("progress-bar").style.width = total ? `${(100 * round) / total}%` : "0%";
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
  for (const post of posts.slice(0, 10)) {
    const div = document.createElement("div");
    div.className = `post ${post.stance}${post.reply_to ? " reply" : ""}`;
    const replyTag = post.reply_to
      ? `<span class="post-reply-tag">↩ ${esc(post.reply_to)}</span>` : "";
    div.innerHTML = `
      <div class="post-head">
        <span>${post.avatar}</span>
        <span class="post-name">${esc(post.author)}</span>
        <span class="post-handle">${esc(post.handle)} · ${esc(post.archetype)}</span>
        ${replyTag}
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
  $("composer-note").textContent = "";
  state.totalRounds = Number($("rounds").value);
  setProgress(0, state.totalRounds);
  setStatus("running", "Starting…");

  try {
    const wantLlm = $("use-llm").checked;
    const sim = await api("/simulations", "POST", {
      topic: $("topic").value.trim(),
      n_agents: Number($("n-agents").value),
      bias: Number($("bias").value),
      use_llm: wantLlm,
    });
    state.simId = sim.id;
    $("composer-note").textContent =
      wantLlm && !sim.llm_active
        ? "LLM unavailable on the server — falling back to template posts."
        : "";
    renderMetrics(sim.metrics, 0);
    onSimCreated(sim);

    for (let round = 1; round <= state.totalRounds; round++) {
      setStatus("running", `Running — round ${round}/${state.totalRounds}`);
      setProgress(round, state.totalRounds);
      const step = await api(`/simulations/${state.simId}/step`, "POST");
      renderPosts(step.posts);
      renderMetrics(step.metrics, step.round);
      onStep(step);
      await sleep(650);
    }
    setStatus("done", "Finished");
    await onFinished();
  } catch (err) {
    setStatus("idle", "Error");
    $("composer-note").textContent = `Something went wrong: ${err.message}`;
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
