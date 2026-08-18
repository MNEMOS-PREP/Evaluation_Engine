/**
 * Student view vs developer view.
 *
 * This module has two audiences with genuinely opposed needs. A student must
 * never see a raw 0–4 while the display gate is closed — that is §6.7, and it
 * is the module's central promise. A developer building the ensemble cannot
 * work without seeing exactly that number, plus spread, tokens and cost.
 *
 * The wrong resolution is to leak the number into the student surface with a
 * disclaimer beside it. People read the number and skip the disclaimer, and
 * the promise becomes decorative. So the two views are a real switch, the
 * student one is the default, and every gated value is rendered by
 * `Judgement` which reads this — no component decides on its own.
 *
 * A tiny external store rather than context: the switch is read in the
 * transcript, the margin and the shell at once, and a provider wrapping all
 * three would re-render the transcript on every toggle of anything.
 */

const KEY = "m13.devMode";
const listeners = new Set<() => void>();

let devMode = readInitial();

function readInitial(): boolean {
  if (typeof window === "undefined") return false;
  // A URL flag wins on first load, so a bug report can carry the view it was
  // filed from: /turns/<id>?dev=1
  const fromUrl = new URLSearchParams(window.location.search).get("dev");
  if (fromUrl === "1") return true;
  if (fromUrl === "0") return false;
  return window.localStorage.getItem(KEY) === "1";
}

export function setDevMode(next: boolean): void {
  if (next === devMode) return;
  devMode = next;
  window.localStorage.setItem(KEY, next ? "1" : "0");
  listeners.forEach((listener) => listener());
}

export function subscribeDevMode(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getDevMode(): boolean {
  return devMode;
}
