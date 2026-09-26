import { api } from "./api.js";
import { h, icon, toast } from "./dom.js";
import { EngineStore, renderEngineList, renderProviderCards } from "./engines.js";
import { Feed } from "./feed.js";
import { SheetGrid } from "./grid.js";
import { Recorder } from "./recorder.js";
import { getPreference, initTheme, setPreference } from "./theme.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const store = new EngineStore();
let grid;
let feed;
let book = { loaded: false };
let preview = null; // { id, handle, sheet, data, cells, diff }
let busy = false;
let voiceState = "idle";

// --- workbook ---------------------------------------------------------------

function renderBook(data) {
  book = data;
  $("#file-name").textContent = data.loaded ? data.name : "No workbook";
  $("#file-btn").title = data.loaded ? data.path : "";
  $("#undo-btn").disabled = !data.can_undo || Boolean(preview);
  $("#redo-btn").disabled = !data.can_redo || Boolean(preview);
  $$("[data-needs-book]").forEach((el) => { el.disabled = !data.loaded; });
  $("#empty-state").hidden = data.loaded;
  $("#grid").hidden = !data.loaded;
  renderTabs();
  if (data.loaded && data.sheet && !preview) grid.show(data.sheet, { mode: "live" });
}

function renderTabs() {
  const nav = $("#sheet-tabs");
  if (!book.loaded) { nav.replaceChildren(); return; }
  const changed = preview?.diff || {};
  const names = preview ? Object.keys(changed).filter((n) => changed[n].status !== "removed") : book.sheets.map((s) => s.name);
  const active = preview ? preview.sheet : book.active;
  nav.replaceChildren(...names.map((name) => {
    const d = changed[name];
    const mark = d && d.status !== "unchanged" ? h("span", { class: `tab-dot tab-${d.status}` }) : null;
    return h("button", {
      class: "sheet-tab", type: "button", "aria-current": name === active ? "page" : null,
      disabled: Boolean(preview) && name !== active,
      onclick: () => switchSheet(name),
    }, name, mark);
  }));
}

async function switchSheet(name) {
  if (preview || name === book.active) return;
  try { renderBook(await api.setActive(name)); } catch (e) { toast(e.message, "error"); }
}

async function openWith(promise, label) {
  try {
    discardPreview(false);
    renderBook(await promise);
    feed.note(`Opened ${book.name}${label ? ` ${label}` : ""}`);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function onCellEdit(row, col, value, revert) {
  try {
    const state = await api.editCell(book.active, row, col, value);
    if (book.sheet?.rows[row]) book.sheet.rows[row][col] = value;
    book = { ...book, ...state, sheet: book.sheet };
    $("#undo-btn").disabled = !state.can_undo;
    $("#redo-btn").disabled = !state.can_redo;
  } catch (e) {
    revert();
    toast(e.message, "error");
  }
}

async function undo() {
  if (preview || !book.can_undo) return;
  try { renderBook(await api.undo()); toast("Undone"); } catch (e) { toast(e.message, "error"); }
}

async function redo() {
  if (preview || !book.can_redo) return;
  try { renderBook(await api.redo()); toast("Redone"); } catch (e) { toast(e.message, "error"); }
}

// --- preview ----------------------------------------------------------------

function enterPreview(res, handle) {
  preview = { id: res.proposal_id, handle, sheet: res.preview.sheet, diff: res.diff };
  const d = res.diff[res.preview.sheet] || {};
  grid.show(res.preview.data, { mode: "preview", cells: res.preview.cells, addedColumns: d.added_columns || [] });
  $("#preview-text").textContent = res.explanation || "Review the highlighted changes.";
  $("#preview-bar").hidden = false;
  $("#app").classList.add("is-preview");
  $("#undo-btn").disabled = $("#redo-btn").disabled = true;
  renderTabs();
}

function exitPreview() {
  preview = null;
  $("#preview-bar").hidden = true;
  $("#app").classList.remove("is-preview");
}

async function acceptPreview() {
  if (!preview) return;
  const { id, handle } = preview;
  try {
    const state = await api.accept(id);
    exitPreview();
    renderBook(state);
    handle.settle("Applied", "pill-accent");
    toast("Changes applied and saved", "success");
  } catch (e) {
    toast(e.message, "error");
    discardPreview(false);
  }
}

function discardPreview(notify = true) {
  if (!preview) return;
  const { id, handle } = preview;
  api.reject(id).catch(() => {});
  exitPreview();
  handle.settle("Discarded", "");
  renderBook(book);
  if (notify) toast("Discarded");
}

// --- commands ---------------------------------------------------------------

async function runCommand(text, { voice } = {}) {
  text = text.trim();
  if (!text || busy) return;
  if (!book.loaded) { toast("Open a workbook first", "error"); return; }
  if (!store.primary("code")) {
    toast("No code engine is ready. Add a key in Settings.", "error");
    openSettings("providers");
    return;
  }
  discardPreview(false);
  busy = true;
  setVoiceState("thinking");
  feed.user(text, { voice });
  const primary = store.primary("code");
  const pending = feed.pending(`Writing code with ${primary.engine.name}…`);
  try {
    const res = await api.command(text);
    pending.done();
    const handle = feed.response(res, {
      accept: acceptPreview,
      reject: () => discardPreview(),
      retry: () => runCommand(text),
    });
    if (res.status === "proposal" && res.preview) enterPreview(res, handle);
  } catch (e) {
    pending.done();
    feed.error(e.message, { retry: () => runCommand(text), attempts: e.body?.attempts });
  } finally {
    busy = false;
    setVoiceState("idle");
    store.refresh().catch(() => {});
  }
}

// --- voice ------------------------------------------------------------------

const recorder = new Recorder({
  onLevel: (level) => $("#mic").style.setProperty("--level", level.toFixed(3)),
  onAutoStop: (reason) => {
    if (voiceState !== "listening") return;
    if (reason === "no-speech") {
      recorder.cancel();
      setVoiceState("idle", "Didn't hear anything. Tap to try again");
    } else {
      stopListening();
    }
  },
});

const VOICE_COPY = {
  idle: ["Tap to talk", "or hold Space anywhere"],
  listening: ["Listening…", "pauses end the recording · Esc cancels"],
  transcribing: ["Transcribing…", ""],
  thinking: ["Working on it…", ""],
};

function setVoiceState(state, message) {
  voiceState = state;
  const mic = $("#mic");
  mic.dataset.state = state;
  mic.setAttribute("aria-pressed", String(state === "listening"));
  mic.setAttribute("aria-label", state === "listening" ? "Stop recording" : "Start voice command");
  mic.disabled = state === "transcribing" || state === "thinking";
  const [status, hint] = VOICE_COPY[state];
  $("#voice-status").textContent = message || status;
  const hintEl = $("#voice-hint");
  if (state === "idle" && !message) {
    hintEl.replaceChildren("or hold ", h("kbd", {}, "Space"), " anywhere");
  } else {
    hintEl.textContent = hint;
  }
  if (state === "listening") {
    const voice = store.primary("voice");
    if (voice) hintEl.textContent = `${voice.engine.name} · ${hint}`;
  }
}

async function startListening(mode) {
  if (voiceState !== "idle" || busy) return;
  if (!book.loaded) { toast("Open a workbook first", "error"); return; }
  if (!store.primary("voice")) {
    toast("No voice engine is ready. Add a key in Settings.", "error");
    openSettings("voice");
    return;
  }
  try {
    setVoiceState("listening");
    await recorder.start(mode);
  } catch (e) {
    setVoiceState("idle");
    const denied = e.name === "NotAllowedError";
    toast(denied ? "Microphone access was blocked. Allow it in the browser's address bar." : e.message, "error");
  }
}

async function stopListening() {
  if (voiceState !== "listening") return;
  setVoiceState("transcribing");
  let blob;
  try {
    blob = await recorder.stop();
  } catch (e) {
    setVoiceState("idle");
    toast(e.message, "error");
    return;
  }
  if (!blob) { setVoiceState("idle", "Didn't catch that. Try again"); return; }
  try {
    const res = await api.transcribe(blob);
    const text = (res.text || "").trim();
    if (!text) { setVoiceState("idle", "Didn't catch that. Try again"); return; }
    setVoiceState("idle");
    if (store.settings.auto_run) {
      runCommand(text, { voice: res });
    } else {
      const input = $("#text-input");
      input.value = text;
      autoGrow(input);
      input.focus();
      toast("Transcript ready. Edit it, then press Enter");
    }
  } catch (e) {
    setVoiceState("idle");
    feed.error(e.message, { attempts: e.body?.attempts });
  } finally {
    store.refresh().catch(() => {});
  }
}

function cancelListening() {
  if (voiceState !== "listening") return;
  recorder.cancel();
  setVoiceState("idle", "Cancelled");
}

// --- engine chips -----------------------------------------------------------

function renderChips() {
  for (const kind of ["code", "voice"]) {
    const chip = $(`#chip-${kind}`);
    const primary = store.primary(kind);
    const cooling = primary && store.settings.cooldowns?.[primary.item.id];
    chip.querySelector(".chip-value").textContent = primary ? primary.engine.name : "Not set up";
    chip.dataset.state = !primary ? "error" : cooling ? "warn" : "ok";
    chip.title = primary
      ? `${kind === "code" ? "Code" : "Voice"}: ${primary.engine.name} via ${store.provider(primary.engine.provider).name} (click to change)`
      : "No engine ready (click to set up)";
  }
}

// --- preferences ------------------------------------------------------------

const LANGS = [["en", "English"], ["auto", "Detect automatically"], ["hi", "Hindi"], ["bn", "Bengali"], ["es", "Spanish"],
  ["fr", "French"], ["de", "German"], ["pt", "Portuguese"], ["it", "Italian"], ["ja", "Japanese"], ["ko", "Korean"], ["zh", "Chinese"]];

function renderPrefs(container) {
  const s = store.settings;
  const save = (patch) => store.save(patch).catch((e) => toast(e.message, "error"));
  const toggle = (key, title, desc) => h("label", { class: "pref" },
    h("div", {}, h("div", { class: "pref-title" }, title), h("div", { class: "pref-desc" }, desc)),
    h("input", { type: "checkbox", class: "switch", checked: s[key], onchange: (e) => save({ [key]: e.target.checked }) }));

  const select = h("select", { class: "input", onchange: (e) => save({ language: e.target.value }) },
    LANGS.map(([v, label]) => h("option", { value: v, selected: s.language === v }, label)));

  const theme = h("select", { class: "input", onchange: (e) => setPreference(e.target.value) },
    [["system", "Match system"], ["light", "Light"], ["dark", "Dark"]].map(([v, label]) =>
      h("option", { value: v, selected: getPreference() === v }, label)));

  container.replaceChildren(
    h("label", { class: "pref" },
      h("div", {}, h("div", { class: "pref-title" }, "Theme"), h("div", { class: "pref-desc" }, "Also available from the top bar.")),
      theme),
    h("label", { class: "pref" },
      h("div", {}, h("div", { class: "pref-title" }, "Spoken language"), h("div", { class: "pref-desc" }, "Setting it explicitly is faster and more accurate than auto-detect.")),
      select),
    toggle("auto_run", "Run voice commands immediately", "Turn off to review and edit the transcript before it runs."),
    toggle("fallback", "Fall back to the next engine", "If an engine is rate-limited or down, try the next one in your list."),
    toggle("self_heal", "Auto-fix code errors", "If generated code fails, ask the model to fix it once. Uses one extra request."),
  );
}

// --- settings drawer --------------------------------------------------------

function openSettings(tab = "providers") {
  const drawer = $("#settings");
  renderProviderCards(store, $("#set-providers"), { onChange: () => renderProviderCards(store, $("#set-providers"), { onChange: () => {} }) });
  renderSettingsLists();
  renderPrefs($("#set-prefs"));
  selectTab(tab);
  drawer.hidden = false;
  $("#settings-scrim").hidden = false;
  requestAnimationFrame(() => drawer.classList.add("open"));
  store.refresh().catch(() => {});
  $("#settings-close").focus();
}

function renderSettingsLists() {
  if ($("#settings").hidden && $("#onboarding").hidden) return;
  renderEngineList(store, $("#set-code"), "code");
  renderEngineList(store, $("#set-voice"), "voice");
}

function closeSettings() {
  const drawer = $("#settings");
  drawer.classList.remove("open");
  $("#settings-scrim").hidden = true;
  setTimeout(() => { drawer.hidden = true; }, 200);
}

function selectTab(tab) {
  $$("#settings [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  $$("#settings [data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== tab; });
}

// --- onboarding -------------------------------------------------------------

let obStep = 1;

function showOnboarding() {
  $("#onboarding").hidden = false;
  gotoStep(1);
}

function gotoStep(step) {
  obStep = step;
  $$("#onboarding .ob-step").forEach((s) => { s.hidden = Number(s.dataset.step) !== step; });
  $$("#ob-steps li").forEach((li) => {
    const n = Number(li.dataset.step);
    li.dataset.state = n < step ? "done" : n === step ? "current" : "todo";
  });
  if (step === 1) renderProviderCards(store, $("#ob-providers"), { onChange: updateObFooter });
  if (step === 2) renderObLists();
  if (step === 3) renderPrefs($("#ob-prefs"));
  $("#ob-back").hidden = step === 1;
  $("#ob-next").hidden = step === 3;
  updateObFooter();
}

function renderObLists() {
  renderEngineList(store, $("#ob-code"), "code");
  renderEngineList(store, $("#ob-voice"), "voice");
}

function updateObFooter() {
  const hint = $("#ob-hint");
  const next = $("#ob-next");
  if (obStep === 1) {
    next.disabled = !store.anyKey;
    hint.textContent = store.anyKey ? "" : "Add at least one key to continue";
  } else if (obStep === 2) {
    const code = store.primary("code");
    const voice = store.primary("voice");
    next.disabled = !code;
    hint.textContent = !code ? "Enable a code engine that has a key"
      : !voice ? "No voice engine ready. You can still type requests" : `Code: ${code.engine.name} · Voice: ${voice.engine.name}`;
  } else {
    hint.textContent = "";
  }
}

async function finishOnboarding(action) {
  await store.save({ onboarded: true });
  $("#onboarding").hidden = true;
  if (action === "sample") openWith(api.openSample());
  else $("#file-input").click();
}

// --- wiring -----------------------------------------------------------------

function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
}

function isTyping(target) {
  return target.closest?.("input, textarea, select, [contenteditable], .ag-cell-inline-editing, dialog[open]");
}

function wire() {
  // file menu
  const menu = $("#file-menu");
  const pop = $(".menu-pop", menu);
  const setMenu = (open) => { pop.hidden = !open; $("#file-btn").setAttribute("aria-expanded", String(open)); };
  $("#file-btn").addEventListener("click", (e) => { e.stopPropagation(); setMenu(pop.hidden); });
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) setMenu(false); });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    setMenu(false);
    const action = btn.dataset.action;
    if (action === "upload") $("#file-input").click();
    if (action === "sample") openWith(api.openSample(), "(a copy; the original is untouched)");
    if (action === "download") window.location.href = "/api/workbook/download";
    if (action === "open-path") { $("#path-dialog").showModal(); $("#path-input").focus(); }
  });

  $("#file-input").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) openWith(api.upload(file));
    e.target.value = "";
  });

  $("#path-form").addEventListener("submit", (e) => {
    const path = $("#path-input").value.trim();
    if (path) openWith(api.openPath(path), "(edits save to this file)");
  });
  $("#path-cancel").addEventListener("click", () => $("#path-dialog").close());

  // drag & drop
  const pane = $(".sheet-pane");
  let dragDepth = 0;
  pane.addEventListener("dragenter", (e) => { if (e.dataTransfer?.types.includes("Files")) { dragDepth++; $("#drop-hint").hidden = false; } });
  pane.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#drop-hint").hidden = true; });
  pane.addEventListener("dragover", (e) => e.preventDefault());
  pane.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    $("#drop-hint").hidden = true;
    const file = e.dataTransfer.files[0];
    if (file) openWith(api.upload(file));
  });

  // toolbar
  $("#undo-btn").addEventListener("click", undo);
  $("#redo-btn").addEventListener("click", redo);
  $("#settings-btn").addEventListener("click", () => openSettings());
  $("#chip-code").addEventListener("click", () => openSettings("code"));
  $("#chip-voice").addEventListener("click", () => openSettings("voice"));
  $("#preview-accept").addEventListener("click", acceptPreview);
  $("#preview-reject").addEventListener("click", () => discardPreview());

  // settings drawer
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-scrim").addEventListener("click", closeSettings);
  $$("#settings [role=tab]").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));

  // onboarding
  $("#ob-next").addEventListener("click", () => gotoStep(Math.min(3, obStep + 1)));
  $("#ob-back").addEventListener("click", () => gotoStep(Math.max(1, obStep - 1)));
  $$("[data-finish]").forEach((b) => b.addEventListener("click", () => finishOnboarding(b.dataset.finish)));

  // composer
  const input = $("#text-input");
  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("#text-form").requestSubmit();
    }
  });
  $("#text-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    if (!text.trim() || busy) return;
    input.value = "";
    autoGrow(input);
    runCommand(text);
  });

  $("#mic").addEventListener("click", () => {
    if (voiceState === "listening") stopListening();
    else startListening("auto");
  });

  // keyboard
  let spaceHeld = false;
  document.addEventListener("keydown", (e) => {
    const modalOpen = !$("#onboarding").hidden || !$("#settings").hidden;
    if (e.key === "Escape") {
      if (!$("#settings").hidden) { closeSettings(); return; }
      if (voiceState === "listening") { cancelListening(); return; }
      if (preview && !isTyping(e.target)) { discardPreview(); return; }
    }
    if (modalOpen || isTyping(e.target)) return;
    if (e.code === "Space" && !e.repeat && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      if (voiceState === "idle") { spaceHeld = true; startListening("hold"); }
      return;
    }
    if (e.key === "Enter" && preview) { e.preventDefault(); acceptPreview(); return; }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "z" && !e.shiftKey && !e.target.closest(".ag-root")) { e.preventDefault(); undo(); }
    if (mod && ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y") && !e.target.closest(".ag-root")) { e.preventDefault(); redo(); }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && spaceHeld) {
      e.preventDefault();
      spaceHeld = false;
      stopListening();
    }
  });
  window.addEventListener("blur", () => { if (spaceHeld) { spaceHeld = false; stopListening(); } });
}

async function main() {
  initTheme();
  if (!window.agGrid) {
    document.body.prepend(h("div", { class: "fatal" }, icon("alert"),
      "The spreadsheet component couldn't load from cdn.jsdelivr.net. Check your internet connection and reload."));
    return;
  }
  grid = new SheetGrid($("#grid"), { onEdit: onCellEdit });
  feed = new Feed($("#feed"), { onExample: (text) => runCommand(text) });
  wire();
  setVoiceState("idle");

  try {
    await store.load();
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  store.on(() => {
    renderChips();
    if (!$("#settings").hidden) renderSettingsLists();
    if (!$("#onboarding").hidden && obStep === 2) renderObLists();
    if (!$("#onboarding").hidden) updateObFooter();
  });
  renderChips();

  renderBook(await api.workbook());
  if (!store.settings.onboarded) showOnboarding();
}

main();
