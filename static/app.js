const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LEVELS = ["instant", "easy", "moderate", "hard", "gated"];
const ACTOR = { agent: "🤖 Agent can do", developer: "🧑 You", either: "🤖/🧑 Either" };
const CONF = { verified: "✓ quote found in source", partial: "◐ partly verified", unsupported: "✗ no verified source" };
let library = [], filter = "all";

function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 1800);
}
function store(key, val) { try { if (val === undefined) return JSON.parse(localStorage.getItem(key) || "null"); localStorage.setItem(key, JSON.stringify(val)); } catch { return null; } }

/* ---------- library ---------- */
async function loadLibrary() {
  library = await (await fetch("/api/guides")).json();
  library.sort((a, b) => LEVELS.indexOf(a.difficulty) - LEVELS.indexOf(b.difficulty) || a.app_name.localeCompare(b.app_name));
  renderFilters(); renderLibrary();
}
function renderFilters() {
  const opts = ["all", ...LEVELS];
  $("#filters").innerHTML = opts.map((o) => `<button data-f="${o}" class="${o === filter ? "on" : ""}">${o}</button>`).join("");
  $("#filters").onclick = (e) => { if (e.target.dataset.f) { filter = e.target.dataset.f; renderFilters(); renderLibrary(); } };
}
function renderLibrary() {
  const rows = library.filter((g) => filter === "all" || g.difficulty === filter);
  $("#library").innerHTML = rows.length ? rows.map((g) => `
    <a class="card" href="/g/${g.slug}">
      <span class="name">${esc(g.app_name)}</span>
      <span class="badge d-${g.difficulty}">${g.difficulty}</span>
      <span class="meta wait" title="${esc(g.approval_wait)}">Setup ${esc(g.setup_time)} · Approval ${esc(g.approval_wait)}</span>
      <span class="meta">${esc(g.category || "")} ${g.reviewed ? '<span class="pill rev">human-checked</span>' : '<span class="pill">agent-generated</span>'}${g.model_tier === "fallback" ? ' <span class="pill warn">fallback model</span>' : ""}</span>
    </a>`).join("") : `<p class="empty">No guides here yet.</p>`;
}

/* ---------- live generation ---------- */
function generate(q, force = false) {
  const btn = $("#search button"); btn.disabled = true;
  $("#live").hidden = false; $("#live-name").textContent = q; $("#log").innerHTML = "";
  const log = (k, m, cls = "") => { const li = document.createElement("li"); li.className = cls; li.innerHTML = `<span class="k">${esc(k)}</span> ${esc(m)}`; $("#log").appendChild(li); li.scrollIntoView({ block: "nearest" }); };
  log("start", "Checking the library…");
  const es = new EventSource(`/api/generate?q=${encodeURIComponent(q)}${force ? "&force=1" : ""}`);
  es.addEventListener("progress", (e) => { const d = JSON.parse(e.data); log(d.kind, d.msg); });
  es.addEventListener("done", (e) => {
    const d = JSON.parse(e.data); es.close(); btn.disabled = false;
    log("done", d.cached ? "Found in the library" : "Guide ready", "ok");
    setTimeout(() => navigate(`/g/${d.slug}`), d.cached ? 200 : 700);
  });
  es.addEventListener("fail", (e) => { es.close(); btn.disabled = false; log("error", JSON.parse(e.data).message, "fail"); });
  es.onerror = () => { if (es.readyState === 2) return; es.close(); btn.disabled = false; log("error", "Connection lost", "fail"); };
}
$("#search").onsubmit = (e) => { e.preventDefault(); generate($("#q").value.trim()); };

/* ---------- guide ---------- */
function evidence(item) {
  const ev = item.evidence || [];
  if (!ev.length) return `<div class="ev conf-unsupported">✗ no source quoted. Treat as unverified.</div>`;
  const ids = [...new Set(ev.map((e) => e.source_id))].map((i) => `S${i}`).join(", ");
  return `<details class="ev"><summary><span class="conf-${item.confidence}">${CONF[item.confidence]}</span> · ${ids} ▾</summary>
    ${ev.map((e) => `<blockquote class="quote ${e.verified ? "" : "bad"}">“${esc(e.quote)}” <a href="${esc(e.url)}" target="_blank" rel="noopener">S${e.source_id}</a>${e.verified ? "" : " · <b>not found verbatim</b>"}</blockquote>`).join("")}
  </details>`;
}
function meter(d) {
  const n = LEVELS.indexOf(d) + 1;
  return `<div class="meter">${LEVELS.map((l, i) => `<i style="${i < n ? `background:var(--${d})` : ""}"></i>`).join("")}</div>`;
}

async function showGuide(slug) {
  const r = await fetch(`/api/guides/${slug}`);
  if (!r.ok) { $("#guide").innerHTML = `<p>No guide for “${esc(slug)}”. <a href="/">Back to search</a></p>`; return; }
  const g = await r.json();
  document.title = `${g.app_name} OAuth setup guide · OAuth Pathfinder`;
  const doneKey = `done:${g.slug}`, done = new Set(store(doneKey) || []);
  const s = g.evidence_stats || {};
  const checklist = (arr, prefix, fn) => arr.map((x, i) => {
    const id = `${prefix}${i}`;
    return `<div class="row ${done.has(id) ? "done" : ""}"><input type="checkbox" data-id="${id}" ${done.has(id) ? "checked" : ""} aria-label="mark done">${fn(x, i)}</div>`;
  }).join("");

  $("#guide").innerHTML = `
  <div class="g-head">
    <div>
      <a href="/" class="small">← All guides</a>
      <h1>${esc(g.app_name)}: OAuth app setup &amp; approval</h1>
      <div class="small">${esc(g.category)} · ${g.website ? `<a href="${esc(g.website)}" target="_blank" rel="noopener">${esc(g.website)}</a> · ` : ""}
        ${g.review && !g.review.stale ? `<span class="pill rev">human-checked ${esc(g.review.date || "")}</span>` : `<span class="pill">agent-generated</span>`}
        · ${esc(g.generated_at.slice(0, 10))}</div>
    </div>
    <div class="actions">
      <button class="ghost" id="copy-link">Copy share link</button>
      <a class="btn ghost" href="/g/${g.slug}.md" download="${g.slug}-oauth-guide.md">Download .md</a>
      <button class="ghost" id="copy-md">Copy as Markdown</button>
      <button class="ghost" id="regen" title="Re-run the research agent">Regenerate</button>
    </div>
  </div>

  <div class="verdict">
    <div class="vbox"><div class="lbl">Difficulty</div><div class="val"><span class="badge d-${g.difficulty}">${g.difficulty}</span></div>${meter(g.difficulty)}</div>
    <div class="vbox"><div class="lbl">Hands-on setup</div><div class="val">${esc(g.setup_time)}</div></div>
    <div class="vbox"><div class="lbl">Approval wait</div><div class="val">${esc(g.approval_wait)}</div>
      ${g.timing ? (g.timing.confidence === "unsupported" ? `<div class="small conf-partial">Estimate. No source states this timeline.</div>` : `<div class="small conf-verified">Timeline quoted from source</div>${evidence(g.timing)}`) : ""}</div>
    <div class="vbox"><div class="lbl">Provider review</div><div class="val">${g.approval_required ? "Required" : "Not required"}</div></div>
  </div>
  ${g.model_tier === "fallback" ? `<div class="panel warnbox small">⚠️ <b>Draft quality.</b> Stronger models were unavailable (free-tier quota), so a smaller model wrote this guide. The quotes are still checked against the sources, but the difficulty rating and which steps are marked required are more likely to be wrong. Use “Regenerate” later for a better version.</div>` : ""}
  <p class="summary">${esc(g.summary)}</p>
  <p class="small"><b>Why this rating:</b> ${esc(g.difficulty_reason)}</p>

  ${g.review ? `<div class="panel ${g.review.stale ? "warnbox" : "review"}"><h3>Human verification${g.review.date ? ` · ${esc(g.review.date)}` : ""}</h3>
    ${g.review.stale ? `<p class="small">⚠️ This review was done on an earlier version of the guide. The guide has since been regenerated, so the notes below may no longer match it.</p>` : ""}
    <p>${esc(g.review.summary || "")}</p>
    ${g.review.agent_said ? `<p class="small"><b>Corrected by the reviewer:</b> ${Object.entries(g.review.agent_said).map(([k, v]) => `${esc(k.replace(/_/g, " "))} (agent said “${esc(v)}”)`).join("; ")}</p>` : ""}
    ${(g.review.checked || []).length ? `<b>Checked:</b><ul>${g.review.checked.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
    ${(g.review.corrections || []).length ? `<b>Corrected:</b><ul>${g.review.corrections.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}
    ${(g.review.tested || []).length ? `<b>Tested hands-on:</b><ul>${g.review.tested.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}</div>` : ""}

  <div class="panel">
    <h3>Do you need your own OAuth app yet?</h3>
    ${g.composio ? (g.composio.managed
      ? `<p>✅ <b>Composio has a managed OAuth app for ${esc(g.app_name)}</b> (toolkit <code>${esc(g.composio.toolkit)}</code>). You can prototype today with no setup. Switch to your own app before launch if you need your name on the consent screen, scopes beyond the defaults, or your own rate limit.</p>`
      : `<p>⚠️ <b>No Composio-managed app found for ${esc(g.app_name)}</b>${g.composio.toolkit ? ` (toolkit <code>${esc(g.composio.toolkit)}</code>)` : ""}. You need your own credentials from day one, so start this guide now.</p>`)
      : `<p class="small">Many platforms (e.g. Composio) offer a shared “managed” OAuth app for prototyping. In production you usually want your own, so users see your name on the consent screen and you get your own scopes and rate limit. This guide covers getting your own app ready.</p>`}
  </div>

  <div class="two">
    <div class="panel"><h3>🤖 What an agent can do for you</h3><ul>${g.agent_can_do.map((x) => `<li>${esc(x)}</li>`).join("") || "<li>Nothing automatable was identified.</li>"}</ul></div>
    <div class="panel"><h3>🧑 Where you take over</h3><ul>${g.developer_must_do.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
  </div>

  ${g.capabilities?.length ? `<h2>What will your agent do? Access depends on it</h2>
  <div class="panel"><table class="caps"><thead><tr><th>Capability</th><th>Scopes / product</th><th>Access</th><th>What it takes</th></tr></thead><tbody>
    ${g.capabilities.map((c) => `<tr><td>${esc(c.capability)}</td><td><code>${esc(c.scopes)}</code></td>
      <td><span class="acc acc-${c.access.split(" ")[0].replace("/", "")}">${esc(c.access)}</span></td>
      <td>${esc(c.what_it_takes)}${evidence(c)}</td></tr>`).join("")}</tbody></table></div>` : ""}

  <div class="panel"><h3>Your progress</h3><div class="small"><span id="pct"></span></div><div class="progress"><div id="bar"></div></div></div>

  <h2>Before you start</h2>
  <div class="panel">${checklist(g.requirements, "r", (x) => `<div class="body">${esc(x.text)}${evidence(x)}</div>`) || "<p class='small'>No special prerequisites found.</p>"}</div>

  <h2>Steps</h2>
  <div class="panel">${checklist(g.steps, "s", (x, i) => `<span class="num">${i + 1}</span><div class="body">
      <span class="st-title">${esc(x.title)}</span><span class="actor ${x.actor}">${ACTOR[x.actor]}</span>${x.required === false ? `<span class="actor optional">Optional</span>` : ""}
      <div>${esc(x.text)}</div>${x.url ? `<a class="small" href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)} ↗</a>` : ""}${evidence(x)}</div>`)}</div>

  <h2>Plug it into Composio</h2>
  <div class="panel">
    <p class="small">The same for every app. Composio runs the OAuth flow (authorize, code exchange, token refresh), so you don't build it. <a href="https://composio.dev/auth/notion" target="_blank" rel="noopener">Source: Composio setup guide</a></p>
    <ol class="plain">
      <li>In your ${esc(g.app_name)} OAuth app, register the redirect URI <code>https://backend.composio.dev/api/v3/toolkits/auth/callback</code>. It must match exactly, use HTTPS, and have no trailing slash.</li>
      <li>In the Composio dashboard, create an <b>Auth Config</b> for the ${esc(g.app_name)} toolkit, choose <b>OAuth2</b>, enable <b>“Use your own developer authentication”</b>, and paste the Client ID and Client Secret.</li>
      <li>Copy the Auth Config ID (starts with <code>ac_</code>) and pass it to your session for this toolkit. Toolkits without one keep using Composio's managed app.</li>
      <li>Connect a test account through the Connect Link or Playground, and check that your app's name appears on the consent screen.</li>
    </ol>
  </div>

  ${g.approval_required || g.approval_details ? `<h2>Approval &amp; review</h2><div class="panel warnbox"><p>${esc(g.approval_details || "Review is required; see the steps above.")}</p><p class="small">Expected wait: <b>${esc(g.approval_wait)}</b></p></div>` : ""}

  <h2>Nuances that can bite</h2>
  <div class="panel"><ul class="clean">${g.nuances.map((x) => `<li class="row"><div class="body">${esc(x.text)}${evidence(x)}</div></li>`).join("") || "<li class='small'>None found.</li>"}</ul></div>

  <h2>If you get blocked</h2>
  <div class="panel"><ul class="clean">${g.blockers.map((b) => `<li class="row blk"><div class="body"><div class="issue">⚠ ${esc(b.issue)}</div>
     <div class="small">${esc(b.why_it_happens)}</div><div class="fix"><b>Try:</b> ${esc(b.workaround)}</div>${evidence(b)}</div></li>`).join("") || "<li class='small'>No blockers documented.</li>"}</ul></div>

  <h2>OAuth details</h2>
  <div class="panel kv">
    <span>Developer console</span><span>${g.developer_console_url ? `<a href="${esc(g.developer_console_url)}" target="_blank" rel="noopener">${esc(g.developer_console_url)}</a>` : "<span class='small'>not stated in sources</span>"}</span>
    <span>Authorization URL</span><span>${g.authorization_url ? `<code>${esc(g.authorization_url)}</code>` : "<span class='small'>not stated in sources</span>"}</span>
    <span>Token URL</span><span>${g.token_url ? `<code>${esc(g.token_url)}</code>` : "<span class='small'>not stated in sources</span>"}</span>
    <span>PKCE</span><span>${g.uses_pkce ? "Supported / required" : "Not mentioned"}</span>
  </div>

  <h2>What we could not verify</h2>
  <div class="panel warnbox"><ul>${(g.unverified || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>Nothing flagged by the agent. Still spot-check the evidence marks above.</li>"}</ul></div>

  <h2>How this guide was made</h2>
  <div class="panel">
    <p>The agent read <b>${g.sources.length}</b> pages. Of the quotes it cited, <b>${s.quotes_verified ?? 0}/${s.quotes ?? 0}</b> were found verbatim in those pages.
    Claims: <span class="conf-verified">${s.verified ?? 0} verified</span>, <span class="conf-partial">${s.partial ?? 0} partial</span>, <span class="conf-unsupported">${s.unsupported ?? 0} unsupported</span>. Model: <code>${esc(g.model)}</code>.</p>
    ${g.probes?.length ? `<h3>Live endpoint checks</h3><ul class="clean">${g.probes.map((p) => `<li class="row"><div class="body">${p.ok ? "✅" : "⚠️"} ${esc(p.name)}: <code>${esc(p.url)}</code><div class="small">${esc(p.result)}</div></div></li>`).join("")}</ul>` : `<p class="small">No live endpoint checks ran, because the sources didn't state the authorization or token URLs.</p>`}
    ${g.checklist?.length ? `<h3>Standard questions: covered by official docs?</h3><p class="small">${g.checklist.map((c) => `${c.covered ? "✅" : "❔"} ${esc(c.topic)}`).join(" · ")}</p>` : ""}
    ${g.trace?.length ? `<details><summary><b>Agent trace</b> (${g.trace.length} actions in ${g.trace[g.trace.length - 1].t}s): what it searched, read, skipped and decided</summary>
      <ol class="log trace">${g.trace.map((x) => `<li><span class="k">${esc(x.kind)}</span> ${esc(x.msg)}</li>`).join("")}</ol></details>` : ""}
    <h3>Sources</h3>
    <ol>${g.sources.map((x) => `<li value="${x.id}"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a> <span class="small">(${x.kind === "community" ? "<b>community forum, anecdotal</b>, " : x.official === false ? "<b>third-party</b>, " : "official, "}${x.fetched_via === "reader" ? "via reader" : "direct"})</span></li>`).join("")}</ol>
  </div>`;

  const total = g.requirements.length + g.steps.length;
  const upd = () => { const n = [...done].length; $("#pct").textContent = `${n} of ${total} items done (saved in this browser)`; $("#bar").style.width = `${total ? (100 * n) / total : 0}%`; };
  upd();
  $("#guide").onchange = (e) => {
    const id = e.target.dataset?.id; if (!id) return;
    e.target.checked ? done.add(id) : done.delete(id); e.target.closest(".row").classList.toggle("done", e.target.checked);
    store(doneKey, [...done]); upd();
  };
  $("#copy-link").onclick = () => navigator.clipboard.writeText(location.href).then(() => toast("Link copied"));
  $("#copy-md").onclick = async () => navigator.clipboard.writeText(await (await fetch(`/g/${g.slug}.md`)).text()).then(() => toast("Markdown copied"));
  $("#regen").onclick = () => { navigate("/"); $("#q").value = g.app_name; generate(g.app_name, true); };
}

/* ---------- routing ---------- */
function navigate(path) { history.pushState({}, "", path); route(); }
function route() {
  const m = location.pathname.match(/^\/g\/([^/]+)$/);
  $("#home").hidden = !!m; $("#guide").hidden = !m;
  if (m) { showGuide(decodeURIComponent(m[1])); window.scrollTo(0, 0); }
  else { document.title = "OAuth Pathfinder"; loadLibrary(); }
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a");
  if (a && a.origin === location.origin && /^\/(g\/[^.]+)?$/.test(a.pathname) && !a.hasAttribute("download") && !e.metaKey && !e.ctrlKey) { e.preventDefault(); navigate(a.pathname); }
});
window.onpopstate = route;
route();
