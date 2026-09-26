// Light / dark / system theme. The initial value is applied by an inline script
// in index.html before first paint; this module handles switching.

const KEY = "xcelord.theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");

export function getPreference() {
  try { return localStorage.getItem(KEY) || "system"; } catch { return "system"; }
}

function resolve(pref) {
  return pref === "system" ? (media.matches ? "dark" : "light") : pref;
}

function apply(pref) {
  document.documentElement.dataset.theme = resolve(pref);
  document.documentElement.dataset.themePref = pref;
  document.querySelectorAll("[data-theme-option]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.themeOption === pref));
  });
}

export function setPreference(pref) {
  try { localStorage.setItem(KEY, pref); } catch { /* private mode */ }
  apply(pref);
}

export function initTheme() {
  apply(getPreference());
  media.addEventListener("change", () => {
    if (getPreference() === "system") apply("system");
  });
  document.querySelectorAll("[data-theme-option]").forEach((btn) => {
    btn.addEventListener("click", () => setPreference(btn.dataset.themeOption));
  });
}
