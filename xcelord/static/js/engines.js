// Provider key cards and ranked engine lists, shared by onboarding and settings.

import { api } from "./api.js";
import { h, icon, toast } from "./dom.js";

const USES = {
  openrouter: ["Code"],
  gemini: ["Code", "Voice"],
  groq: ["Code", "Voice"],
  local: ["Voice"],
};

export class EngineStore {
  constructor() {
    this.meta = null;
    this.settings = null;
    this.listeners = new Set();
    this.saveTimer = null;
  }

  async load() {
    [this.meta, this.settings] = await Promise.all([api.meta(), api.settings()]);
    this.emit();
  }

  async refresh() {
    this.settings = await api.settings();
    this.emit();
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit() { this.listeners.forEach((fn) => fn(this)); }

  async save(patch) {
    this.settings = await api.saveSettings(patch);
    this.emit();
  }

  // Debounced save for rapid toggles / reorders.
  saveChainSoon(kind) {
    clearTimeout(this.saveTimer);
    this.emit();
    this.saveTimer = setTimeout(() => {
      this.save({ [`${kind}_engines`]: this.settings[`${kind}_engines`] })
        .catch((e) => toast(e.message, "error"));
    }, 250);
  }

  provider(id) { return this.meta.providers.find((p) => p.id === id); }
  engine(id) {
    return [...this.meta.code_engines, ...this.meta.voice_engines].find((e) => e.id === id);
  }

  hasKey(providerId) {
    if (providerId === "local") return this.meta.local_whisper;
    return Boolean(this.settings.keys[providerId]?.set);
  }

  /** Why an enabled engine can't run right now, or null if it can. */
  blocker(engine) {
    if (engine.provider === "local" && !this.meta.local_whisper) return "Not installed";
    if (engine.provider !== "local" && !this.hasKey(engine.provider)) return `Needs ${this.provider(engine.provider).name} key`;
    return null;
  }

  primary(kind) {
    for (const item of this.settings[`${kind}_engines`]) {
      const engine = this.engine(item.id);
      if (item.enabled && !this.blocker(engine)) return { item, engine };
    }
    return null;
  }

  get anyKey() {
    return ["openrouter", "gemini", "groq"].some((p) => this.hasKey(p));
  }
}

// --- provider cards -----------------------------------------------------------

export function renderProviderCards(store, container, { onChange } = {}) {
  container.replaceChildren();
  for (const provider of store.meta.providers) {
    container.append(providerCard(store, provider, onChange));
  }
}

function providerCard(store, provider, onChange) {
  const keyInfo = store.settings.keys[provider.id] || {};
  const uses = USES[provider.id] || [];
  const status = h("div", { class: "provider-status", "aria-live": "polite" });
  const setStatus = (ok, text) => {
    status.replaceChildren(icon(ok ? "check" : ok === false ? "alert" : "info"), h("span", {}, text));
    status.dataset.state = ok ? "ok" : ok === false ? "error" : "idle";
  };

  const head = h("div", { class: "provider-head" },
    h("div", { class: `provider-logo logo-${provider.id}` }, icon(`logo-${provider.id}`)),
    h("div", { class: "provider-title" },
      h("h3", {}, provider.name),
      h("div", { class: "badges" }, uses.map((u) => h("span", { class: "badge" }, u)))),
  );

  const card = h("article", { class: "provider-card", dataset: { provider: provider.id } },
    head, h("p", { class: "provider-blurb" }, provider.blurb));

  if (provider.id === "local") {
    const installed = store.meta.local_whisper;
    setStatus(installed ? true : null, installed ? "faster-whisper is installed" : "Optional · pip install faster-whisper");
    card.append(status);
    return card;
  }

  const input = h("input", {
    type: "password",
    class: "input",
    placeholder: keyInfo.set ? `Saved key ${keyInfo.hint || ""}` : "Paste API key",
    autocomplete: "off",
    spellcheck: "false",
    "aria-label": `${provider.name} API key`,
    disabled: keyInfo.source === "env",
  });
  const testBtn = h("button", { class: "btn btn-secondary", type: "button" }, "Test & save");
  const removeBtn = keyInfo.set && keyInfo.source === "saved"
    ? h("button", { class: "btn btn-ghost btn-icon", type: "button", title: "Remove key", "aria-label": "Remove key" }, icon("trash"))
    : null;

  if (keyInfo.source === "env") setStatus(true, `Using ${provider.env_var} from environment`);
  else if (keyInfo.set) setStatus(true, `Key saved ${keyInfo.hint || ""}`);
  else setStatus(null, "No key yet");

  const run = async () => {
    const key = input.value.trim();
    if (!key && !keyInfo.set) { setStatus(false, "Paste a key first"); input.focus(); return; }
    testBtn.disabled = true;
    testBtn.textContent = "Testing…";
    try {
      const res = await api.testProvider(provider.id, key || null);
      if (res.ok) {
        if (key) await store.save({ keys: { [provider.id]: key } });
        input.value = "";
        setStatus(true, res.message);
        onChange?.();
      } else {
        setStatus(false, res.message);
      }
    } catch (e) {
      setStatus(false, e.message);
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = "Test & save";
    }
  };
  testBtn.addEventListener("click", run);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(); } });
  removeBtn?.addEventListener("click", async () => {
    await store.save({ keys: { [provider.id]: null } });
    onChange?.();
  });

  card.append(
    h("div", { class: "key-row" }, input, testBtn, removeBtn),
    h("div", { class: "provider-foot" }, status,
      h("a", { href: provider.key_url, target: "_blank", rel: "noopener", class: "link" },
        "Get a free key", icon("external"))),
  );
  return card;
}

// --- ranked engine list -------------------------------------------------------

export function renderEngineList(store, container, kind) {
  const chain = store.settings[`${kind}_engines`];
  const usage = store.settings.usage || {};
  const cooldowns = store.settings.cooldowns || {};
  const primary = store.primary(kind);

  const list = h("ol", { class: "engine-list", "aria-label": `${kind} engines, best first` });
  chain.forEach((item, index) => {
    const engine = store.engine(item.id);
    const provider = store.provider(engine.provider);
    const blocker = store.blocker(engine);
    const isPrimary = primary?.item.id === item.id;
    const used = usage[item.id] || 0;

    const toggle = h("input", {
      type: "checkbox", class: "switch", checked: item.enabled,
      "aria-label": `Use ${engine.name} (${provider.name})`,
      onchange: (e) => { item.enabled = e.target.checked; store.saveChainSoon(kind); },
    });

    const move = (delta) => {
      const target = index + delta;
      if (target < 0 || target >= chain.length) return;
      [chain[index], chain[target]] = [chain[target], chain[index]];
      store.saveChainSoon(kind);
    };

    const modelInput = h("input", {
      class: "input input-sm mono", value: item.model || engine.model, spellcheck: "false",
      "aria-label": `Model id for ${engine.name}`,
      onchange: (e) => {
        const v = e.target.value.trim();
        item.model = v && v !== engine.model ? v : null;
        store.saveChainSoon(kind);
      },
    });

    const state = !item.enabled ? null
      : blocker ? h("span", { class: "pill pill-warn" }, blocker)
      : cooldowns[item.id] ? h("span", { class: "pill pill-warn" }, `Rate limited · ${cooldowns[item.id]}s`)
      : isPrimary ? h("span", { class: "pill pill-accent" }, "In use")
      : h("span", { class: "pill" }, "Fallback");

    list.append(h("li", { class: `engine-row${item.enabled ? "" : " is-off"}` },
      h("span", { class: "rank" }, String(index + 1)),
      toggle,
      h("div", { class: "engine-main" },
        h("div", { class: "engine-title" },
          h("strong", {}, engine.name),
          h("span", { class: "muted" }, provider.name),
          h("span", { class: `badge ${engine.free ? "badge-free" : "badge-paid"}` }, engine.free ? "Free" : "Paid"),
          state),
        h("div", { class: "engine-sub" },
          h("span", {}, engine.limits),
          used ? h("span", {}, ` · ${used}${engine.daily_cap ? ` / ${engine.daily_cap}` : ""} today`) : null),
        h("div", { class: "engine-note" }, engine.note),
        h("details", { class: "engine-model" }, h("summary", {}, "Model"), modelInput)),
      h("div", { class: "engine-move" },
        h("button", { class: "btn btn-ghost btn-icon", type: "button", "aria-label": `Move ${engine.name} up`, disabled: index === 0, onclick: () => move(-1) }, icon("chevron-up")),
        h("button", { class: "btn btn-ghost btn-icon", type: "button", "aria-label": `Move ${engine.name} down`, disabled: index === chain.length - 1, onclick: () => move(1) }, icon("chevron-down"))),
    ));
  });
  container.replaceChildren(list);
}
