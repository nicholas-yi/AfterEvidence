"use strict";

const byId = (id) => document.getElementById(id);
let packs = [];
let currentPack = "project";
let snapshot = null;
let token = "";
let pending = 0;
let refreshTask = null;
let displayedAnswerEpoch = null;
const drafts = new Map();

function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function subject() { return byId("subject").value.trim(); }
function sameSubject(value) { return value.trim().toLowerCase() === subject().toLowerCase(); }
function activePack() { return packs.find((pack) => pack.id === currentPack); }

function notify(message) {
  byId("notice").textContent = message;
  byId("notice").hidden = !message;
}

function showError(error) {
  console.error(error);
  byId("error").textContent = error instanceof Error ? error.message : String(error);
  byId("error").hidden = false;
}

function clearAnswer(message = "Evidence changed. Ask again for a current answer.") {
  displayedAnswerEpoch = null;
  byId("answer").replaceChildren(node("p", message, "muted"));
}

function setBusy(change) {
  pending += change;
  byId("activity").hidden = pending === 0;
  byId("note-form").setAttribute("aria-busy", String(pending > 0));
  byId("ask-form").setAttribute("aria-busy", String(pending > 0));
  for (const id of ["wake", "sleep", "load-example", "ask", "subject"]) byId(id).disabled = pending > 0;
  for (const button of byId("packs").querySelectorAll("button")) button.disabled = pending > 0;
}

async function api(path, method = "GET", data = null) {
  const headers = {};
  if (method !== "GET") {
    headers["X-AfterEvidence-Token"] = token;
    if (data !== null) headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { method, headers, body: data === null ? null : JSON.stringify(data) });
  let value;
  try { value = await response.json(); }
  catch (error) { throw new Error(`The local server returned an invalid response (HTTP ${response.status}).`); }
  if (!response.ok) throw new Error(value.error || `Local operation failed (HTTP ${response.status}).`);
  return value;
}

async function operation(message, task, mutation = false) {
  byId("error").hidden = true;
  if (mutation) clearAnswer("Memory update requested. Ask again once the operation finishes.");
  setBusy(1);
  notify(message);
  try { await task(); }
  catch (error) { showError(error); notify("Operation did not complete. Inspect failed notes and use Retry when appropriate."); }
  finally {
    setBusy(-1);
    try { await refresh(true); } catch (error) { showError(error); }
  }
}

async function checkModel() {
  const status = await api("/api/status");
  token = status.csrf_token;
  packs = status.packs;
  const badge = byId("model-status");
  badge.textContent = status.model_available ? `${status.model} / local` : "Local model unavailable";
  badge.className = status.model_available ? "pill" : "pill bad";
  if (!status.model_available) showError(new Error(status.model_error));
  renderPacks();
}

function renderPacks() {
  byId("packs").replaceChildren(...packs.map((pack) => {
    const button = node("button", pack.title);
    button.type = "button";
    button.setAttribute("aria-pressed", String(pack.id === currentPack));
    button.disabled = pending > 0;
    button.addEventListener("click", async () => {
      drafts.set(currentPack, {
        subject: byId("subject").value, title: byId("note-title").value, text: byId("note-text").value,
        session: byId("note-session").value, question: byId("question").value, mode: byId("answer-mode").value,
      });
      currentPack = pack.id;
      snapshot = null;
      const draft = drafts.get(pack.id);
      byId("subject").value = draft ? draft.subject : pack.subject;
      byId("note-title").value = draft ? draft.title : "";
      byId("note-text").value = draft ? draft.text : "";
      byId("note-session").value = draft ? draft.session : "notes";
      byId("question").value = draft ? draft.question : pack.question;
      byId("answer-mode").value = draft ? draft.mode : "repaired";
      byId("pack-label").textContent = pack.title.toUpperCase();
      byId("pack-description").textContent = pack.description;
      byId("note-text").placeholder = pack.examples[0];
      byId("error").hidden = true;
      notify("");
      clearAnswer("Add evidence, then ask a question or run Sleep / repair.");
      renderPacks();
      try { await refresh(true); } catch (error) { showError(error); }
    });
    return button;
  }));
}

async function refresh(force = false) {
  while (refreshTask) {
    if (!force) return;
    await refreshTask;
  }
  const task = (async () => {
    const pack = currentPack;
    const next = await api(`/api/state?pack=${encodeURIComponent(pack)}`);
    if (pack !== currentPack) return;
    if (displayedAnswerEpoch !== null && displayedAnswerEpoch !== next.epoch) clearAnswer();
    const changed = !snapshot || snapshot.epoch !== next.epoch;
    snapshot = next;
    if (changed || force) renderState();
  })();
  refreshTask = task;
  try { await task; }
  finally { if (refreshTask === task) refreshTask = null; }
}

function sourceButton(id) {
  const source = snapshot.episodes.find((episode) => episode.id === id);
  const button = node("button", source && source.status === "active" ? source.title : `Source ${id.slice(0, 10)}`, "source-chip");
  button.type = "button";
  button.title = id;
  button.addEventListener("click", (event) => {
    const target = document.getElementById(`source-${id}`);
    for (const item of byId("sources").children) item.classList.remove("highlight");
    if (target) {
      target.classList.add("highlight");
      target.tabIndex = -1;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches || event.detail === 0;
      target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
      target.focus({ preventScroll: true });
    }
    else notify("This source is not active in the selected subject.");
  });
  return button;
}

function renderSources(episodes) {
  byId("source-summary").textContent = `${episodes.length} active`;
  const elements = episodes.map((episode) => {
    const item = node("article", "", "source");
    item.id = `source-${episode.id}`;
    const top = node("div", "", "claim-top");
    top.append(node("strong", episode.title), node("span", episode.extraction_status,
      episode.extraction_status === "ready" ? "pill" : "pill warn"));
    item.append(top, node("p", episode.text), node("div",
      `${episode.created_at} | session: ${episode.session} | ${episode.id.slice(0, 12)}`, "metadata"));
    if (episode.error) item.append(node("p", episode.error, "danger"));
    const actions = node("div", "", "actions");
    if (episode.extraction_status !== "ready") {
      const retry = node("button", "Retry extraction");
      retry.type = "button";
      retry.addEventListener("click", () => operation("Qwen is retrying this source...", async () => {
        await api(`/api/episodes/${episode.id}/extract`, "POST");
        notify("Extraction completed.");
      }, true));
      actions.append(retry);
    } else {
      const reread = node("button", "Re-read note");
      reread.type = "button";
      reread.addEventListener("click", () => {
        if (!confirm("Re-read with the current model? This replaces the source version and refreshes dependent memories.")) return;
        operation("Qwen is re-reading the note with the current extraction contract...", async () => {
          await api(`/api/episodes/${episode.id}`, "PATCH", { text: episode.text });
          notify("Note re-read. Inspect the assertions and run Sleep / repair if needed.");
        }, true);
      });
      actions.append(reread);
    }
    const edit = node("button", "Correct source");
    edit.type = "button";
    edit.addEventListener("click", () => {
      if (item.querySelector("textarea")) return;
      const editor = node("textarea");
      editor.value = episode.text;
      editor.maxLength = 4000;
      editor.setAttribute("aria-label", `Correct ${episode.title}`);
      const save = node("button", "Save correction");
      const cancel = node("button", "Cancel");
      save.type = cancel.type = "button";
      const controls = node("div", "", "actions");
      controls.append(save, cancel);
      cancel.addEventListener("click", () => { editor.remove(); controls.remove(); });
      save.addEventListener("click", () => operation("Replacing the source and repairing affected memory...", async () => {
        await api(`/api/episodes/${episode.id}`, "PATCH", { text: editor.value });
        notify("Source replaced. Unsupported content was cleared; run Sleep / repair to reconsider model memories.");
      }, true));
      item.append(editor, controls);
      editor.focus();
    });
    const remove = node("button", "Delete source", "danger");
    remove.type = "button";
    remove.addEventListener("click", () => {
      if (!confirm("Delete this source and clear unsupported application content? This cannot be undone.")) return;
      operation("Removing source evidence...", async () => {
        await api(`/api/episodes/${episode.id}`, "DELETE");
        notify("Source deleted. Independent surviving support is preserved.");
      }, true);
    });
    actions.append(edit, remove);
    item.append(actions);
    return item;
  });
  byId("sources").replaceChildren(...(elements.length ? elements : [node("div", "No notes yet. Load an example or add your own observation.", "empty")]));
}

function claimCard(claim) {
  const card = node("article", "", `claim ${claim.origin === "rule" ? "rule" : "model"} ${claim.status !== "live" ? "inactive" : ""}`);
  const head = node("div", "", "claim-top");
  head.append(node("span", claim.kind === "fact" ? claim.relation.replaceAll("_", " ") : `${claim.kind} / ${claim.origin}`, "kind"),
    node("span", claim.status, claim.status === "live" ? "pill" : "pill warn"));
  card.append(head, node("p", claim.value || "Content cleared after source removal.", "value"));
  card.append(node("span", claim.origin === "rule" ? "Explicit application rule; review before acting." :
    `Model self-rating: ${Math.round(claim.confidence * 100)}% (uncalibrated)`, "confidence"));
  if (claim.reason) card.append(node("p", claim.reason, "muted"));
  const details = node("details");
  details.append(node("summary", "Evidence and dependencies"));
  details.append(node("p", claim.id, "node-id"));
  claim.proofs.forEach((proof, index) => {
    if (index) details.append(node("span", "OR", "muted"));
    const line = node("div", "", "proof");
    proof.forEach((source, position) => {
      if (position) line.append(node("span", "AND", "join"));
      line.append(sourceButton(source));
    });
    details.append(line);
  });
  for (const [source, quote] of Object.entries(claim.quotes)) {
    details.append(sourceButton(source), node("p", quote, "quote"));
  }
  if (claim.origin === "qwen-sleep") details.append(node("p",
    "Host-assigned input lineage: every current fact supplied for this subject is a dependency. This tracks inputs, not semantic truth.", "muted"));
  card.append(details);
  if (claim.origin !== "rule" && claim.value) {
    const review = node("button", claim.status === "rejected" ? "Restore for review" : "Reject model claim", "quiet danger");
    review.type = "button";
    review.addEventListener("click", () => {
      const reject = claim.status !== "rejected";
      if (!confirm(reject ? "Exclude this model interpretation? The source note stays available." :
        "Restore this interpretation for review? Source and conflict checks still apply.")) return;
      operation("Applying your review decision...", async () => {
        await api(`/api/claims/${claim.id}/review`, "POST", { reject });
        notify(reject ? "Model claim rejected; source preserved. Show inactive history to restore it." :
          "Claim restored for review, subject to current evidence and conflicts.");
      }, true);
    });
    card.append(review);
  }
  return card;
}

function renderState() {
  if (!snapshot) return;
  byId("subject-options").replaceChildren(...Array.from(new Set(snapshot.episodes
    .filter((episode) => episode.status === "active").map((episode) => episode.subject))).sort().map((name) => {
    const option = node("option", name);
    option.value = name;
    return option;
  }));
  const episodes = snapshot.episodes.filter((episode) => episode.status === "active" && sameSubject(episode.subject));
  const relevant = snapshot.claims.filter((claim) => sameSubject(claim.subject));
  const current = relevant.filter((claim) => claim.status === "live");
  byId("source-count").textContent = episodes.length;
  byId("fact-count").textContent = current.filter((claim) => claim.kind === "fact").length;
  byId("memory-count").textContent = current.filter((claim) => claim.kind !== "fact").length;
  byId("dirty-count").textContent = relevant.filter((claim) => ["dirty", "conflict"].includes(claim.status)).length;
  byId("epoch").textContent = snapshot.epoch;
  renderSources(episodes);
  const visible = relevant.filter((claim) => byId("show-inactive").checked || ["live", "dirty", "conflict"].includes(claim.status));
  for (const [id, filter] of [["facts", (claim) => claim.kind === "fact"], ["memories", (claim) => claim.kind !== "fact"]]) {
    const cards = visible.filter(filter).map(claimCard);
    byId(id).replaceChildren(...(cards.length ? cards : [node("div", id === "facts" ?
      "Quoted assertions appear after Qwen reads a source." : "Rule plans appear automatically. Run Sleep / repair for model-generated summaries and hypotheses.", "empty")]));
  }
  byId("warnings").replaceChildren(...snapshot.warnings.map((warning) => node("p", warning)));
  const metrics = snapshot.calls.map((call) => ({ ...JSON.parse(call.metrics), error: call.error }));
  const tokens = metrics.reduce((total, call) => total + (Number.isFinite(call.prompt_tokens) ? call.prompt_tokens + call.output_tokens : 0), 0);
  const unknownUsage = metrics.filter((call) => !Number.isFinite(call.prompt_tokens)).length;
  byId("call-summary").textContent = `Last ${metrics.length} logged calls / ${tokens} recorded tokens${unknownUsage ? ` / ${unknownUsage} usage unknown` : ""}`;
  byId("events").replaceChildren(...snapshot.events.map((event) => {
    const row = node("div", "", "event");
    row.append(node("strong", `Epoch ${event.epoch}: ${event.kind}`), node("div", event.created_at, "muted"),
      node("code", `${event.entity_id || "subject operation"} ${event.detail}`));
    return row;
  }));
}

byId("note-form").addEventListener("submit", (event) => {
  event.preventDefault();
  operation("Qwen is reading the note locally...", async () => {
    const result = await api("/api/episodes", "POST", {
      pack: currentPack, subject: subject(), text: byId("note-text").value,
      title: byId("note-title").value.trim() || "Observation", session: byId("note-session").value,
    });
    byId("note-text").value = "";
    byId("note-title").value = "";
    notify(result.warnings.length ? result.warnings.join("\n") : `Wake completed: ${result.extracted} quoted assertions extracted.`);
  }, true);
});

byId("load-example").addEventListener("click", () => operation("Loading synthetic example notes with local Qwen...", async () => {
  const pack = activePack();
  const existing = snapshot.episodes.filter((episode) => episode.status === "active" && sameSubject(episode.subject));
  if (existing.length && !confirm("This subject already has notes. Add the example as additional sources?")) {
    notify("Example load cancelled.");
    return;
  }
  const exampleSession = `example-${pack.id}`;
  byId("note-session").value = exampleSession;
  for (let index = 0; index < pack.examples.length; index += 1) {
    notify(`Qwen is reading example ${index + 1} of ${pack.examples.length}...`);
    const exampleText = pack.examples[index].replaceAll(pack.subject, () => subject());
    const result = await api("/api/episodes", "POST", { pack: currentPack, subject: subject(), text: exampleText,
      title: `${pack.title} example ${index + 1}`, session: exampleSession });
    if (result.warnings.length) notify(result.warnings.join("\n"));
    await refresh(true);
  }
  notify("Example notes processed. Review the extracted relations and any missing-input warnings, then run Sleep / repair.");
}, true));

byId("sleep").addEventListener("click", () => operation("Qwen is consolidating this subject's current evidence...", async () => {
  const result = await api("/api/sleep", "POST", { pack: currentPack, subject: subject() });
  notify([`Sleep completed: ${result.cards} usable source-linked memories. No parameter training was performed.`,
    ...result.warnings].join("\n"));
}, true));

byId("ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  operation("Qwen is answering from fresh current context...", async () => {
    const result = await api("/api/ask", "POST", { pack: currentPack, subject: subject(),
      question: byId("question").value, mode: byId("answer-mode").value });
    await refresh(true);
    if (result.epoch !== snapshot.epoch) throw new Error("The answer used an older evidence epoch and was discarded. Ask again.");
    displayedAnswerEpoch = result.epoch;
    const metadata = `${result.unknown ? "Evidence gap" : "Source-cited answer"} / ${result.mode} / epoch ${result.epoch}` +
      (result.metrics ? ` / ${result.metrics.seconds.toFixed(1)}s local inference` : " / no model called");
    byId("answer").replaceChildren(node("div", metadata, "answer-meta"), node("div", result.answer, "answer-text"));
    const citations = node("div", "", "proof");
    for (const source of result.citations) citations.append(sourceButton(source));
    byId("answer").append(citations);
    for (const warning of result.warnings) byId("answer").append(node("p", warning, "muted"));
    notify("Answer completed. Citations show its available input sources, not a guarantee of semantic correctness.");
  });
});

byId("delete-session").addEventListener("click", () => {
  const session = byId("note-session").value;
  if (!confirm(`Delete all sources in session "${session}" for this use-case pack, including other subjects in that session?`)) return;
  operation("Deleting the selected session...", async () => {
    await api("/api/sessions/delete", "POST", { pack: currentPack, session });
    notify("Session sources deleted and affected memory repaired.");
  }, true);
});

byId("check-model").addEventListener("click", async () => {
  byId("error").hidden = true;
  try { await checkModel(); notify("Local Ollama status refreshed."); } catch (error) { showError(error); }
});
byId("subject").addEventListener("change", () => { clearAnswer("Subject changed. Ask from its current evidence."); renderState(); });
byId("show-inactive").addEventListener("change", renderState);

async function initialize() {
  setBusy(1);
  try {
    await checkModel();
    const pack = activePack();
    byId("pack-label").textContent = pack.title.toUpperCase();
    byId("pack-description").textContent = pack.description;
    byId("question").value = pack.question;
    byId("note-text").placeholder = pack.examples[0];
    await refresh(true);
  } finally { setBusy(-1); }
  setInterval(async () => { try { await refresh(); } catch (error) { showError(error); } }, 3000);
}
initialize().catch(showError);
