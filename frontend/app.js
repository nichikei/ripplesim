/* RippleSim dashboard logic: create a simulation, step it round by round,
   render the live feed and metrics. */

const $ = (id) => document.getElementById(id);

const state = {
  simId: null,
  running: false,
  totalRounds: 12,
  agents: [],
  report: null,
};

/* ---- slider labels ---- */
for (const [slider, label] of [
  ["n-agents", "n-agents-value"],
  ["bias", "bias-value"],
  ["rounds", "rounds-value"],
]) {
  $(slider).addEventListener("input", () => ($(label).textContent = $(slider).value));
}

/* ---- capabilities: configure the UI for what the server can actually do ---- */
(async () => {
  try {
    const caps = await api("/capabilities");
    const toggle = $("use-llm");
    if (caps.llm_available) {
      // The server has a key — use it by default. Nobody wants canned
      // template posts when real ones are one flag away.
      toggle.checked = true;
      $("use-llm-switch").title =
        `Agents write their own posts (${caps.models.posts}); ` +
        `interviews and the report use ${caps.models.report}.`;
    } else {
      toggle.checked = false;
      toggle.disabled = true;
      $("use-llm-label").textContent = "AI posts (no API key)";
      $("use-llm-switch").title =
        "Set ANTHROPIC_API_KEY on the server to let agents write their own posts.";
    }
  } catch {
    /* server not reachable yet — leave the toggle as authored */
  }
})();

/* ---- status helpers ---- */
function setStatus(mode, text) {
  const pill = $("status-pill");
  pill.className = `pill pill-${mode}`;
  pill.textContent = text;
}

function setProgress(round, total) {
  $("progress-bar").style.width = total ? `${(100 * round) / total}%` : "0%";
}

const MODES = {
  ai: ["🧠 AI-written", "mode-ai"],
  template: ["📋 Template mode", "mode-template"],
  failing: ["⚠️ LLM failing — templates", "mode-failing"],
};

function setModeBadge(mode) {
  const [text, cls] = MODES[mode];
  const badge = $("mode-badge");
  badge.textContent = text;
  badge.className = `mode-badge ${cls}`;
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
      ? `<span class="post-reply-tag">${post.is_rebuttal ? "⚔ answering" : "↩"} ${esc(post.reply_to)}</span>`
      : "";
    div.innerHTML = `
      <div class="post-head">
        <span>${post.avatar}</span>
        <span class="post-name">${esc(post.author)}</span>
        <span class="post-handle">${esc(post.handle)} · ${esc(post.archetype)}</span>
        ${replyTag}
        <span class="post-round">R${post.round}</span>
      </div>
      ${post.parent_text ? `<div class="post-quote">${esc(post.parent_text)}</div>` : ""}
      <div class="post-text">${esc(post.text)}</div>
      <div class="post-meta">❤️ ${post.likes} · 🔁 ${post.shares}</div>`;
    if (!post.is_event && post.author_id !== undefined) {
      div.classList.add("clickable");
      div.title = "Interview this agent";
      div.addEventListener("click", () => {
        const agent = state.agents[post.author_id];
        if (agent) openChat(agent);
      });
    }
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
  $("mode-badge").classList.remove("hidden");
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
    state.agents = sim.agents;
    state.llmActive = sim.llm_active;

    setModeBadge(sim.llm_active ? "ai" : "template");

    $("composer-note").textContent =
      wantLlm && !sim.llm_active
        ? "LLM unavailable on the server — falling back to template posts."
        : sim.llm_active
        ? "AI mode: agents write their own posts, so each round takes a few seconds."
        : "Template mode: posts come from canned phrases. Turn on AI posts for real writing.";
    renderMetrics(sim.metrics, 0);
    onSimCreated(sim);

    for (let round = 1; round <= state.totalRounds; round++) {
      setStatus("running", `Running — round ${round}/${state.totalRounds}`);
      setProgress(round, state.totalRounds);
      const step = await api(`/simulations/${state.simId}/step`, "POST");
      state.agents = step.agents;
      if (state.llmActive && step.llm_written === 0) {
        // Asked for AI posts and got none — say so rather than quietly
        // serving templates that look like a broken simulation.
        setModeBadge("failing");
        $("composer-note").textContent =
          "Every AI call failed this round — check the server logs (an invalid or " +
          "expired ANTHROPIC_API_KEY is the usual cause). Showing template posts.";
      }
      renderPosts(step.posts);
      renderMetrics(step.metrics, step.round);
      onStep(step);
      // In LLM mode the round already takes seconds; the pacing delay is only
      // there to make instant template rounds readable.
      if (!state.llmActive) await sleep(650);
    }
    // The report agent investigates the simulation before writing — this can
    // take a few seconds, so keep the user informed rather than looking stalled.
    setStatus("running", "Writing report…");
    await onFinished();
    setStatus("done", "Finished");
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

/* ---- full report modal ---- */
const reportModal = () => $("report-modal");

$("open-report").addEventListener("click", () => reportModal().classList.remove("hidden"));
for (const el of document.querySelectorAll("[data-close-report]")) {
  el.addEventListener("click", () => reportModal().classList.add("hidden"));
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    reportModal().classList.add("hidden");
    $("chat-drawer").classList.add("hidden");
  }
});

$("download-report").addEventListener("click", () => {
  if (state.simId) window.location.href = `/api/simulations/${state.simId}/report.md`;
});

$("print-report").addEventListener("click", () => window.print());

/* ---- agent interview chat ---- */
const chat = { agentId: null, history: [] };

function openChat(agent) {
  chat.agentId = agent.id;
  chat.history = [];
  const stance = (agent.opinion >= 0 ? "+" : "") + Number(agent.opinion).toFixed(2);
  $("chat-avatar").textContent = agent.avatar;
  $("chat-name").textContent = `${agent.name} ${agent.handle}`;
  $("chat-sub").textContent = `${agent.archetype} · stance ${stance} · ${agent.followers ?? "?"} followers`;
  $("chat-messages").innerHTML =
    `<div class="chat-note">You're interviewing a simulated agent. Ask why they believe what they believe — or what would change their mind.</div>`;
  $("chat-drawer").classList.remove("hidden");
  $("chat-input").focus();
}

function addChatMsg(cls, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${cls}`;
  div.textContent = text;
  $("chat-messages").appendChild(div);
  $("chat-messages").scrollTop = 1e9;
  return div;
}

$("chat-close").addEventListener("click", () => $("chat-drawer").classList.add("hidden"));

$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = $("chat-input").value.trim();
  if (!message || chat.agentId === null || !state.simId) return;
  $("chat-input").value = "";
  addChatMsg("user", message);
  const typing = addChatMsg("agent typing", "…");
  try {
    const res = await api(
      `/simulations/${state.simId}/agents/${chat.agentId}/chat`, "POST",
      { message, history: chat.history }
    );
    typing.remove();
    addChatMsg("agent", res.reply);
    chat.history.push({ role: "user", content: message },
                      { role: "assistant", content: res.reply });
  } catch (err) {
    typing.remove();
    addChatMsg("agent error", err.message.includes("503")
      ? "LLM is not available — start the server with ANTHROPIC_API_KEY set to interview agents."
      : `Something went wrong: ${err.message}`);
  }
});

/* Extension hooks — implemented by charts.js (kept as no-ops until then). */
let onSimCreated = () => {};
let onStep = () => {};
let onInject = () => {};
let onFinished = async () => {};

$("run-btn").addEventListener("click", runSimulation);
$("inject-btn").addEventListener("click", injectEvent);
