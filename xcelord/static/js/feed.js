// Conversation panel: user turns, results, previews, errors.

import { formatMs, h, icon } from "./dom.js";

const EXAMPLES = [
  "Add a Bonus column that is 10% of Sales",
  "What are total sales by department?",
  "Sort by Sales, highest first",
  "Create a summary sheet with the average sale per month",
  "Remove rows where Sales is below 5000",
];

export class Feed {
  constructor(el, { onExample } = {}) {
    this.el = el;
    this.onExample = onExample;
    this.renderWelcome();
  }

  renderWelcome() {
    this.el.replaceChildren(h("div", { class: "welcome" },
      h("div", { class: "welcome-icon" }, icon("sparkle")),
      h("h2", {}, "Ask for anything"),
      h("p", {}, "Speak or type a request. Xcelord writes the code, shows you a preview of the change, and only applies it when you accept."),
      h("div", { class: "examples" }, EXAMPLES.map((text) =>
        h("button", { class: "example", type: "button", onclick: () => this.onExample?.(text) }, text))),
    ));
    this.welcome = true;
  }

  _add(node) {
    if (this.welcome) { this.el.replaceChildren(); this.welcome = false; }
    this.el.append(node);
    node.scrollIntoView({ block: "end", behavior: "smooth" });
    return node;
  }

  user(text, { voice } = {}) {
    const meta = voice ? h("div", { class: "msg-meta" }, icon("mic"), `${voice.engine_name} · ${formatMs(voice.ms)}`, fallbackNote(voice)) : null;
    return this._add(h("div", { class: "msg msg-user" }, h("div", { class: "bubble" }, text), meta));
  }

  pending(label) {
    const timer = h("span", { class: "elapsed" }, "0.0 s");
    const labelEl = h("span", {}, label);
    const node = this._add(h("div", { class: "msg msg-bot pending" },
      h("div", { class: "card" }, h("div", { class: "thinking" }, h("span", { class: "dots" }, h("i"), h("i"), h("i")), labelEl, timer))));
    const start = performance.now();
    const interval = setInterval(() => { timer.textContent = `${((performance.now() - start) / 1000).toFixed(1)} s`; }, 100);
    return {
      node,
      setLabel: (text) => { labelEl.textContent = text; },
      done: () => { clearInterval(interval); node.remove(); },
    };
  }

  response(res, handlers = {}) {
    const status = {
      proposal: ["Preview ready", "pill-accent"],
      answer: ["Answer", ""],
      clarify: ["Needs detail", "pill-warn"],
      error: ["Couldn't run", "pill-danger"],
    }[res.status] || ["Done", ""];

    const body = [];
    if (res.explanation) body.push(h("p", { class: "explanation" }, res.explanation));
    if (res.result) body.push(renderResult(res.result));
    if (res.output) body.push(h("pre", { class: "output" }, res.output));
    if (res.status === "error") body.push(h("pre", { class: "output output-error" }, res.error));

    let actions = null;
    if (res.status === "proposal") {
      const summary = diffSummary(res.diff);
      if (summary) body.push(h("p", { class: "diff-summary" }, summary));
      actions = h("div", { class: "card-actions" },
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => handlers.reject?.() }, "Discard"),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => handlers.accept?.() }, icon("check"), "Apply"));
    }
    if (res.status === "error" || res.status === "clarify") {
      actions = h("div", { class: "card-actions" },
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => handlers.retry?.() }, icon("refresh"), "Try again"));
    }

    const code = res.code ? h("details", { class: "code" },
      h("summary", {}, icon("code"), res.repaired ? "Code (auto-fixed after an error)" : "Code"),
      h("pre", {}, h("code", {}, res.code))) : null;

    const node = this._add(h("div", { class: `msg msg-bot status-${res.status}` },
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("span", { class: `pill ${status[1]}` }, status[0])),
        body, code, actions),
      h("div", { class: "msg-meta" }, icon("cpu"), `${res.engine_name} · ${formatMs(res.ms)}`, fallbackNote(res))));
    return {
      node,
      settle: (label, cls) => {
        node.querySelector(".card-actions")?.remove();
        const pill = node.querySelector(".card-head .pill");
        pill.textContent = label;
        pill.className = `pill ${cls || ""}`;
      },
    };
  }

  error(message, { retry, attempts } = {}) {
    const list = attempts?.length ? h("ul", { class: "attempts" }, attempts.map((a) =>
      h("li", {}, h("strong", {}, a.name), `: ${a.error || "ok"}`))) : null;
    return this._add(h("div", { class: "msg msg-bot status-error" },
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("span", { class: "pill pill-danger" }, "Error")),
        h("p", { class: "explanation" }, message), list,
        retry ? h("div", { class: "card-actions" },
          h("button", { class: "btn btn-ghost", type: "button", onclick: retry }, icon("refresh"), "Try again")) : null)));
  }

  note(text) {
    return this._add(h("div", { class: "msg msg-note" }, text));
  }
}

function fallbackNote(res) {
  const failed = (res.attempts || []).filter((a) => !a.ok);
  if (!failed.length) return null;
  return h("span", { class: "fallback", title: failed.map((a) => `${a.name}: ${a.error}`).join("\n") },
    ` · fell back from ${failed.map((a) => a.name).join(", ")}`);
}

function diffSummary(diff) {
  if (!diff) return "";
  const parts = [];
  for (const [name, d] of Object.entries(diff)) {
    if (d.status === "unchanged") continue;
    if (d.status === "added") { parts.push(`new sheet “${name}”`); continue; }
    if (d.status === "removed") { parts.push(`delete sheet “${name}”`); continue; }
    const bits = [];
    if (d.added_columns.length) bits.push(`+${d.added_columns.length} column${d.added_columns.length > 1 ? "s" : ""}`);
    if (d.removed_columns.length) bits.push(`−${d.removed_columns.length} column${d.removed_columns.length > 1 ? "s" : ""}`);
    if (d.rows_after !== d.rows_before) bits.push(`${d.rows_before} → ${d.rows_after} rows`);
    const edited = d.changed - (d.added_columns.length * d.rows_after);
    if (edited > 0) bits.push(`${edited.toLocaleString()} cell${edited > 1 ? "s" : ""} changed`);
    if (!bits.length) bits.push("reordered");
    parts.push(`“${name}”: ${bits.join(", ")}`);
  }
  return parts.join(" · ");
}

function renderResult(result) {
  if (result.type === "value") {
    const v = typeof result.value === "number"
      ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(result.value)
      : String(result.value);
    return h("div", { class: "result-value" }, v);
  }
  const fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const rows = result.rows.slice(0, 50);
  const table = h("table", { class: "result-table" },
    h("thead", {}, h("tr", {}, result.columns.map((c) => h("th", {}, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, j) =>
      h("td", { class: result.types[j] === "number" ? "num" : "" },
        v == null ? "" : typeof v === "number" ? fmt.format(v) : String(v)))))));
  const more = result.total_rows > rows.length
    ? h("div", { class: "muted small" }, `Showing ${rows.length} of ${result.total_rows.toLocaleString()} rows`) : null;
  return h("div", { class: "result-wrap" }, table, more);
}
