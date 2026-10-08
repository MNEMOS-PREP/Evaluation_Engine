/**
 * The app shell: a thin top bar and a wide content area.
 *
 * Why a top bar and not M15's rail. That module is used one company at a time
 * and every screen is *about* that company, so the rail holds the context. Here
 * the context is a single turn, and the turn IS the page — the answer is the
 * widest thing on screen and a permanent 240px rail would eat the measure the
 * transcript needs. So the chrome gets one line at the top and gets out of the
 * way.
 *
 * The view switch lives here rather than on the turn page because it changes
 * what every screen is allowed to show, and burying that in one screen's
 * header is how it ends up applied inconsistently.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

import { DependencyAlert } from "@ai/core";

import { useDeps, useHealth } from "../api";
import { getDevMode, setDevMode, subscribeDevMode } from "./devMode";
import { Pill } from "./primitives";

export function useDevMode(): boolean {
  return useSyncExternalStore(subscribeDevMode, getDevMode, () => false);
}

const NAV = [
  { to: "/score", label: "Score" },
  { to: "/rubrics", label: "Rubrics" },
  { to: "/calibration", label: "Calibration" },
  { to: "/disputes", label: "Disputes" },
  { to: "/raters", label: "Raters" },
  { to: "/outbox", label: "Outbox" },
  { to: "/deps", label: "Dependencies" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("m13.theme") as "light" | "dark") || "light",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("m13.theme", theme);
  }, [theme]);

  return (
    <button
      type="button"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="rounded-md px-2 py-1 text-ink-soft transition-colors hover:bg-surface-sunken hover:text-ink"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      <span aria-hidden className="text-sm">
        {theme === "dark" ? "☀" : "☾"}
      </span>
    </button>
  );
}

/**
 * The view switch.
 *
 * Labelled with what each view *is* rather than "advanced mode", because the
 * distinction is not seniority — it is whether the numbers on screen have
 * passed the display gate.
 */
function ViewSwitch() {
  const dev = useDevMode();
  return (
    <div
      role="group"
      aria-label="View"
      className="flex items-center rounded-md border border-line p-0.5"
    >
      {[
        { on: false, label: "Student", hint: "What a candidate sees. The display gate applies." },
        {
          on: true,
          label: "Developer",
          hint: "Raw 0–4 scores, spread, tokens and cost. Not a student surface.",
        },
      ].map((option) => (
        <button
          key={option.label}
          type="button"
          title={option.hint}
          aria-pressed={dev === option.on}
          onClick={() => setDevMode(option.on)}
          className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
            dev === option.on
              ? "bg-brand-soft text-brand"
              : "text-ink-faint hover:text-ink-soft"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const health = useHealth();
  const deps = useDeps();

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/90 backdrop-blur">
        <div className="mx-auto flex h-13 max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5">
          <Link to="/score" className="flex shrink-0 items-center gap-2.5">
            <span
              aria-hidden
              className="grid h-6.5 w-6.5 place-items-center rounded-md bg-brand text-xs font-bold text-white"
            >
              ai
            </span>
            <span className="text-sm font-semibold text-ink">Evaluation Engine</span>
          </Link>

          <nav aria-label="Main" className="flex flex-wrap items-center gap-0.5">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  [
                    "rounded-md px-2.5 py-1 text-sm transition-colors",
                    isActive
                      ? "bg-surface-sunken font-medium text-ink"
                      : "text-ink-soft hover:bg-surface-sunken hover:text-ink",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {/* Scoring is the one feature that switches off without a key, and
                the header says so rather than letting a student discover it
                when the button does nothing. */}
            {deps.data && !deps.data.evaluation_available && (
              <Pill tone="reported" title="No API key is configured, so no new answer can be scored.">
                scoring off
              </Pill>
            )}
            {health.data && (
              <span
                className="provenance hidden lg:inline"
                title={`rubrics ${health.data.rubric_set_version}`}
              >
                {/* A count, not the set: nine rubrics made the set a line
                    longer than the bar (2026-10-08). The set is the title. */}
                {health.data.rubric_set_version.split("+").length} rubrics · calibration{" "}
                {health.data.calibration_version}
              </span>
            )}
            <ViewSwitch />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 md:px-8 md:py-10">
        {/* Renders nothing when nothing is degraded, so it is always safe to
            include — and when M05 or M12 is down it says which part is off. */}
        <div className="mb-8 empty:mb-0">
          <DependencyAlert degraded={deps.data?.degraded} />
        </div>
        {children}
      </main>

      <footer className="border-t border-line px-5 py-5 md:px-8">
        <p className="provenance mx-auto max-w-6xl">
          M13 · Evaluation Engine — every score here quotes the words that earned it, and no
          number is shown until it has been checked against human raters.
        </p>
      </footer>
    </div>
  );
}
