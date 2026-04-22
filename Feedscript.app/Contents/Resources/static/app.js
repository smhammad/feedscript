const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  posts: [],
  fetchSrc: null,
  job: null,       // { id, src, phases, done, outDir, startedAt, target, total }
};

function show(screenId) {
  $$(".screen").forEach(s => s.classList.add("hidden"));
  $(screenId).classList.remove("hidden");
  $$(".nav-item").forEach(n => n.classList.toggle("active", "#" + n.dataset.screen === screenId));
  if (screenId === "#screen-main") renderBanner();
  if (screenId === "#screen-library") loadLibrary();
}

$$(".nav-item").forEach(btn => {
  btn.onclick = () => show("#" + btn.dataset.screen);
});

function setAuthBar(username) {
  const bar = $("#auth-bar");
  if (username) {
    bar.innerHTML = `<span>Logged in as <strong>${escapeHtml(username)}</strong></span>
      <button id="btn-logout">Log out</button>`;
    $("#btn-logout").onclick = async () => {
      await fetch("/api/auth/logout", { method: "POST" });
      setAuthBar(null);
      show("#screen-login");
    };
  } else {
    bar.innerHTML = "";
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function fmtNum(n) {
  if (n == null) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function fmtDate(iso) { return iso ? iso.slice(0, 10) : "—"; }

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

async function checkAuth() {
  const r = await fetch("/api/auth/status");
  const d = await r.json();
  const nav = $("#app-nav");
  if (d.logged_in) {
    setAuthBar(d.username);
    nav.classList.remove("hidden");
    show("#screen-main");
  } else {
    setAuthBar(null);
    nav.classList.add("hidden");
    show("#screen-login");
  }
}

$$(".tab").forEach(t => {
  t.onclick = () => {
    $$(".tab").forEach(x => x.classList.remove("active"));
    $$(".tab-panel").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    $(`#form-${t.dataset.tab}`).classList.add("active");
  };
});

$("#form-password").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const errEl = $("[data-err]", f);
  errEl.textContent = "";
  const btn = $("button[type=submit]", f);
  btn.disabled = true;
  try {
    const r = await fetch("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: f.username.value.trim(),
        password: f.password.value,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Login failed");
    setAuthBar(d.username);
    show("#screen-main");
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
};

$("#form-cookies").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const errEl = $("[data-err]", f);
  errEl.textContent = "";
  const btn = $("button[type=submit]", f);
  btn.disabled = true;
  try {
    const r = await fetch("/api/auth/cookies_json", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blob: f.blob.value }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Login failed");
    setAuthBar(d.username);
    show("#screen-main");
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
};

$("#form-fetch").onsubmit = (e) => {
  e.preventDefault();
  const f = e.target;
  const target = f.target.value.trim().replace(/^@/, "");
  const limit = parseInt(f.limit.value, 10) || 100;
  if (!target) return;
  startFetch(target, limit, f.date_from.value, f.date_to.value);
};

$("#stop-fetch").onclick = () => {
  if (state.fetchSrc) { state.fetchSrc.close(); state.fetchSrc = null; }
  $("#stop-fetch").disabled = true;
};

function startFetch(target, limit, dateFrom, dateTo) {
  state.posts = [];
  $("#post-table tbody").innerHTML = "";
  $("#post-table").classList.remove("hidden");
  $("#controls").classList.remove("hidden");
  $("#stats").classList.remove("hidden");
  setFetchStatus("Connecting to Instagram…", true);
  updateStats("loading");

  if (state.fetchSrc) state.fetchSrc.close();
  const params = new URLSearchParams({ limit: String(limit) });
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const src = new EventSource(`/api/posts/${encodeURIComponent(target)}?${params}`);
  state.fetchSrc = src;
  $("#stop-fetch").disabled = false;

  src.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.error) {
      setFetchStatus(d.error, false, true);
      src.close(); state.fetchSrc = null;
      $("#stop-fetch").disabled = true;
      return;
    }
    if (d.type === "profile") {
      const info = `@${escapeHtml(d.username)} · ${fmtNum(d.followers)} followers · ${d.posts_count} posts total${d.is_private ? " · private" : ""} · loading videos…`;
      setFetchStatus(info, true);
    } else if (d.type === "post") {
      state.posts.push(d.post);
      if (passesFilters(d.post)) {
        renderRow(d.post, $("#post-table tbody").children.length + 1);
      }
      updateStats("loading");
      const profile = $("#profile-text").textContent.split(" · loading")[0];
      setFetchStatus(`${profile} · ${state.posts.length} loaded`, true);
    } else if (d.type === "done") {
      src.close(); state.fetchSrc = null;
      $("#stop-fetch").disabled = true;
      const profile = $("#profile-text").textContent.split(" · ")[0];
      setFetchStatus(`${profile} · ${state.posts.length} videos loaded`, false);
      updateStats("done");
      applySort();
    }
  };

  src.onerror = () => {
    src.close(); state.fetchSrc = null;
    $("#stop-fetch").disabled = true;
    setFetchStatus("Connection lost", false, true);
    updateStats("done");
  };
}

function setFetchStatus(text, loading, error) {
  const wrap = $("#profile-info");
  const spinner = $("#fetch-spinner");
  const txt = $("#profile-text");
  wrap.classList.remove("hidden");
  if (loading) spinner.classList.remove("hidden");
  else spinner.classList.add("hidden");
  txt.textContent = text;
  txt.style.color = error ? "var(--err)" : "";
}

function updateStats(phase) {
  const n = state.posts.length;
  const withViews = state.posts.filter(p => p.views != null).length;
  const shown = state.posts.filter(passesFilters).length;
  const base = `${n} videos loaded${phase === "loading" ? "…" : ""} · ${withViews} have view counts`;
  $("#stats").textContent = shown === n ? base : `${base} · ${shown} after filters`;
}

function renderRow(p, idx) {
  const tr = document.createElement("tr");
  tr.dataset.shortcode = p.shortcode;
  tr.innerHTML = `
    <td><input type="checkbox" class="post-check" /></td>
    <td class="num">${idx}</td>
    <td><img loading="lazy" src="${escapeHtml(p.thumbnail)}" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" /></td>
    <td class="caption"><div class="cap-text">${escapeHtml(p.caption || "")}</div></td>
    <td class="num">${fmtNum(p.likes)}</td>
    <td class="num">${fmtNum(p.comments)}</td>
    <td class="num">${fmtNum(p.views)}</td>
    <td>${fmtDate(p.timestamp)}</td>
    <td><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">open</a></td>
  `;
  $("#post-table tbody").appendChild(tr);
}

function passesFilters(p) {
  const minLikes = parseInt($("#min-likes").value, 10);
  const minComments = parseInt($("#min-comments").value, 10);
  const minViews = parseInt($("#min-views").value, 10);
  if (Number.isFinite(minLikes) && (p.likes ?? 0) < minLikes) return false;
  if (Number.isFinite(minComments) && (p.comments ?? 0) < minComments) return false;
  if (Number.isFinite(minViews) && (p.views ?? 0) < minViews) return false;
  return true;
}

function applySort() {
  const by = $("#sort-by").value;
  const order = $("#sort-order").value;
  const mult = order === "desc" ? -1 : 1;
  const filtered = state.posts.filter(passesFilters);
  filtered.sort((a, b) => {
    const av = a[by]; const bv = b[by];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (by === "timestamp") return mult * (new Date(av) - new Date(bv));
    return mult * (av - bv);
  });
  const tbody = $("#post-table tbody");
  tbody.innerHTML = "";
  filtered.forEach((p, i) => renderRow(p, i + 1));
  updateStats("done");
  autoCheckTopN();
}

function autoCheckTopN() {
  const n = parseInt($("#take-n").value, 10) || 0;
  $$(".post-check").forEach((cb, i) => { cb.checked = i < n; });
  $("#check-all").checked = false;
}

["#sort-by", "#sort-order"].forEach(s => $(s).onchange = applySort);
["#min-likes", "#min-comments", "#min-views"].forEach(s => $(s).oninput = applySort);
$("#take-n").oninput = autoCheckTopN;

$("#check-all").onchange = (e) => {
  $$(".post-check").forEach(cb => cb.checked = e.target.checked);
};

$("#btn-transcribe").onclick = async () => {
  const rows = [...$("#post-table tbody").querySelectorAll("tr")];
  const selectedCodes = rows
    .filter(r => r.querySelector(".post-check").checked)
    .map(r => r.dataset.shortcode);
  if (!selectedCodes.length) { alert("Select at least one post."); return; }
  const byCode = new Map(state.posts.map(p => [p.shortcode, p]));
  const posts = selectedCodes
    .map(sc => byCode.get(sc))
    .filter(Boolean)
    .map(p => ({
      shortcode: p.shortcode,
      caption: p.caption || "",
      likes: p.likes ?? null,
      comments: p.comments ?? null,
      views: p.views ?? null,
      timestamp: p.timestamp || null,
    }));
  const target = $("#form-fetch").target.value.trim().replace(/^@/, "");
  const model = $("#model").value;
  const runName = $("#run-name").value.trim();
  const outputDir = $("#output-dir").value.trim();
  if (outputDir) localStorage.setItem("igt_output_dir", outputDir);
  startJob({ target, posts, model, run_name: runName || null, output_dir: outputDir || null });
};

(() => {
  const saved = localStorage.getItem("igt_output_dir");
  if (saved) $("#output-dir").value = saved;
})();

function emptyPhases(total) {
  return {
    download:   { total, done: 0, errors: 0, current: null, started: false, finished: false },
    transcribe: { total: 0, done: 0, errors: 0, current: null, started: false, finished: false },
  };
}

async function startJob(body) {
  const r = await fetch("/api/transcribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) { alert("Error: " + (d.detail || r.status)); return; }

  state.job = {
    id: d.job_id,
    src: null,
    phases: emptyPhases(body.posts.length),
    done: false,
    cancelled: false,
    outDir: null,
    target: body.target,
    total: body.posts.length,
    startedAt: Date.now(),
    lastEvent: null,
  };
  openJobStream();
  resetJobScreen();
  show("#screen-job");
}

function openJobStream() {
  if (!state.job || state.job.src) return;
  const src = new EventSource(`/api/transcribe/${state.job.id}/events`);
  state.job.src = src;
  src.onmessage = (ev) => handleJobEvent(JSON.parse(ev.data));
  src.onerror = () => { src.close(); state.job.src = null; };
}

function resetJobScreen() {
  $("#job-log").innerHTML = "";
  $("#job-summary").textContent = "Starting…";
  $("#btn-open-folder").classList.add("hidden");
  $("#btn-cancel").disabled = false;
  ["download", "transcribe"].forEach(ph => updatePhaseUI(ph));
}

function handleJobEvent(e) {
  if (!state.job) return;
  state.job.lastEvent = e;
  const phases = state.job.phases;
  const log = $("#job-log");

  if (e.type === "job_start") {
    phases.download.total = e.total;
    state.job.outDir = e.final_file || e.out_dir;
  } else if (e.type === "phase_start") {
    phases[e.phase].started = true;
    phases[e.phase].total = e.total;
    updatePhaseUI(e.phase);
    appendLog(log, `Phase ${e.phase} — ${e.total} item${e.total === 1 ? "" : "s"}`);
  } else if (e.type === "item_start") {
    phases[e.phase].current = e.shortcode;
    updatePhaseUI(e.phase);
  } else if (e.type === "item_done") {
    const p = phases[e.phase];
    p.done += 1;
    p.current = null;
    updatePhaseUI(e.phase);
    const suffix = e.phase === "download" && e.bytes ? ` (${(e.bytes / 1024 / 1024).toFixed(1)} MB)` : "";
    appendLog(log, `[${e.phase}] ${e.shortcode} ✓${suffix}`, "ok");
  } else if (e.type === "item_error") {
    const p = phases[e.phase];
    p.errors += 1;
    p.current = null;
    updatePhaseUI(e.phase);
    appendLog(log, `[${e.phase}] ${e.shortcode}: ${e.error}`, "err");
  } else if (e.type === "item_skip") {
    const p = phases[e.phase];
    p.done += 1;
    p.current = null;
    updatePhaseUI(e.phase);
    appendLog(log, `[${e.phase}] ${e.shortcode} skipped: ${e.reason}`);
  } else if (e.type === "log") {
    appendLog(log, e.message);
  } else if (e.type === "job_done") {
    state.job.done = true;
    state.job.outDir = e.final_file || e.out_dir;
    ["download", "transcribe"].forEach(ph => { phases[ph].finished = true; updatePhaseUI(ph); });
    appendLog(log, `Finished. Output: ${e.out_dir}`, "ok");
    $("#btn-open-folder").classList.remove("hidden");
    $("#btn-cancel").disabled = true;
    finalizeJobSummary();
  } else if (e.type === "job_error") {
    state.job.done = true;
    appendLog(log, `Job failed: ${e.error}`, "err");
    $("#btn-cancel").disabled = true;
    finalizeJobSummary();
  } else if (e.type === "job_cancelled") {
    state.job.done = true;
    state.job.cancelled = true;
    state.job.outDir = e.final_file || e.out_dir;
    appendLog(log, "Cancelled.", "err");
    $("#btn-open-folder").classList.remove("hidden");
    $("#btn-cancel").disabled = true;
    finalizeJobSummary();
  }
  renderSummary();
  renderBanner();
}

function updatePhaseUI(phaseName) {
  const p = state.job.phases[phaseName];
  const el = $(`.phase[data-phase="${phaseName}"]`);
  if (!el) return;
  const pct = p.total > 0 ? Math.floor(((p.done + p.errors) / p.total) * 100) : 0;
  $("[data-fill]", el).style.width = pct + "%";
  const remaining = Math.max(0, p.total - p.done - p.errors);
  let countText = `${p.done}/${p.total}`;
  if (p.errors) countText += ` · ${p.errors} err`;
  if (remaining && p.started) countText += ` · ${remaining} left`;
  $("[data-count]", el).textContent = countText;
  $("[data-current]", el).textContent = p.current ? `→ ${p.current}` : "";
  el.classList.toggle("active", p.started && !p.finished);
  el.classList.toggle("done", p.finished);
}

function appendLog(log, msg, cls) {
  const li = document.createElement("li");
  li.textContent = msg;
  if (cls) li.className = cls;
  log.appendChild(li);
  log.scrollTop = log.scrollHeight;
}

function renderSummary() {
  if (!state.job) return;
  const elapsed = fmtElapsed(Date.now() - state.job.startedAt);
  const p = state.job.phases;
  const totalDone = p.download.done + p.transcribe.done;
  const totalErr  = p.download.errors + p.transcribe.errors;
  const target = state.job.target;
  const status = state.job.done
    ? (state.job.cancelled ? "Cancelled" : (totalErr ? "Finished with errors" : "Finished"))
    : "Running";
  $("#job-summary").textContent =
    `${status} · @${target} · elapsed ${elapsed} · ${totalDone} done, ${totalErr} errors`;
}

function finalizeJobSummary() {
  renderSummary();
  if (state.job.src) { state.job.src.close(); state.job.src = null; }
  if (_summaryInterval) { clearInterval(_summaryInterval); _summaryInterval = null; }
}

let _summaryInterval = null;
function ensureSummaryTicker() {
  if (_summaryInterval) return;
  _summaryInterval = setInterval(() => {
    if (state.job && !state.job.done) { renderSummary(); renderBanner(); }
  }, 1000);
}

function renderBanner() {
  const banner = $("#job-banner");
  if (!banner) return;
  if (!state.job) { banner.classList.add("hidden"); return; }
  banner.classList.remove("hidden");
  banner.classList.toggle("done", !!state.job.done);
  const p = state.job.phases;
  let label;
  if (state.job.done) {
    label = state.job.cancelled ? "cancelled" : "done";
  } else {
    const parts = [];
    if (p.download.started && !p.download.finished)
      parts.push(`download ${p.download.done}/${p.download.total}`);
    if (p.transcribe.started && !p.transcribe.finished)
      parts.push(`transcribe ${p.transcribe.done}/${p.transcribe.total}`);
    label = parts.length ? parts.join(" · ") : "starting";
  }
  const elapsed = fmtElapsed(Date.now() - state.job.startedAt);
  banner.innerHTML =
    `<span class="label">Transcription job — ${escapeHtml(label)}</span>
     <span class="detail">@${escapeHtml(state.job.target)} · ${elapsed} · click to view</span>`;
  banner.onclick = () => show("#screen-job");
}

$("#btn-back").onclick = () => show("#screen-main");

$("#btn-cancel").onclick = async () => {
  if (!state.job || state.job.done) return;
  if (!confirm("Cancel this job? Progress so far will be kept.")) return;
  await fetch(`/api/transcribe/${state.job.id}/cancel`, { method: "POST" });
  appendLog($("#job-log"), "Cancellation requested…");
};

$("#btn-open-folder").onclick = async () => {
  if (!state.job?.outDir) return;
  await fetch("/api/reveal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: state.job.outDir }),
  });
};

/* ─── Library ─────────────────────────────────────── */

$("#btn-refresh-library").onclick = () => loadLibrary();

async function loadLibrary() {
  const list = $("#library-list");
  list.innerHTML = `<div class="library-empty">Loading…</div>`;
  const outputDir = localStorage.getItem("igt_output_dir") || "";
  const url = "/api/library" + (outputDir ? "?output_dir=" + encodeURIComponent(outputDir) : "");
  try {
    const r = await fetch(url);
    const d = await r.json();
    renderLibrary(d.runs || []);
  } catch (e) {
    list.innerHTML = `<div class="library-empty">Failed to load: ${escapeHtml(e.message || e)}</div>`;
  }
}

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function fmtWhen(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 16);
}

function renderLibrary(runs) {
  const list = $("#library-list");
  if (!runs.length) {
    list.innerHTML = `<div class="library-empty">No transcription runs yet. Runs you complete will appear here.</div>`;
    return;
  }
  list.innerHTML = "";
  for (const run of runs) {
    const row = document.createElement("div");
    row.className = "library-item";
    row.innerHTML = `
      <div class="library-item-head">
        <div class="library-item-title">
          <span class="library-item-name">${escapeHtml(run.run_name)}</span>
          <span class="library-item-target">@${escapeHtml(run.target)}</span>
          ${run.kind === "folder" ? `<span class="library-item-tag">legacy</span>` : ""}
        </div>
        <div class="library-item-meta">
          <span>${run.count ?? "—"} videos</span>
          <span>${run.whisper_model ?? "—"}</span>
          <span>${fmtWhen(run.generated_at)}</span>
          <span>${fmtBytes(run.size)}</span>
        </div>
      </div>
      <div class="library-item-actions"></div>
    `;
    const actions = row.querySelector(".library-item-actions");
    const mkBtn = (label, cls, handler) => {
      const b = document.createElement("button");
      b.className = "ghost" + (cls ? " " + cls : "");
      b.textContent = label;
      b.onclick = handler;
      actions.appendChild(b);
      return b;
    };
    mkBtn("Show in Finder", "", () => libReveal(run));
    if (run.kind === "file") {
      mkBtn("Copy JSON", "", () => libCopy(run));
      mkBtn("Export", "", () => libExport(run));
    }
    mkBtn("Delete", "danger", () => libDelete(run));
    list.appendChild(row);
  }
}

async function libReveal(run) {
  await fetch("/api/reveal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: run.path }),
  });
}

async function libCopy(run) {
  try {
    const r = await fetch("/api/library/file?path=" + encodeURIComponent(run.path));
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Read failed");
    const cr = await fetch("/api/clipboard", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: d.content }),
    });
    if (!cr.ok) {
      try { await navigator.clipboard.writeText(d.content); }
      catch (_) { throw new Error((await cr.json()).detail || "clipboard unavailable"); }
    }
    toast("Copied JSON to clipboard");
  } catch (e) {
    toast("Copy failed: " + (e.message || e));
  }
}

async function libExport(run) {
  try {
    const r = await fetch("/api/library/file?path=" + encodeURIComponent(run.path));
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Read failed");
    const blob = new Blob([d.content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = d.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    toast("Export failed: " + (e.message || e));
  }
}

async function libDelete(run) {
  const label = run.kind === "folder"
    ? `Delete the run folder "${run.run_name}" and all its contents?`
    : `Delete "${run.run_name}.json"?`;
  if (!confirm(label)) return;
  try {
    const r = await fetch("/api/library/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: run.path, kind: run.kind }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Delete failed");
    toast("Deleted");
    loadLibrary();
  } catch (e) {
    toast("Delete failed: " + (e.message || e));
  }
}

function toast(msg) {
  const existing = document.querySelector(".library-toast");
  if (existing) existing.remove();
  const t = document.createElement("div");
  t.className = "library-toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 1800);
}

ensureSummaryTicker();
checkAuth();
