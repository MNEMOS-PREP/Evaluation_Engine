/**
 * Declared here since `@ai/core` 0.7.0 dropped it as "imported by nothing" —
 * M13 imported it, and was still pinned to 0.6.0, so nothing noticed. A module
 * owns its own chrome; the package owns the vocabulary.
 */
export interface NavItem {
  to: string;
  label: string;
}

/** Nav for M13 running standalone. The platform shell supplies its own. */
export const M13_NAV: NavItem[] = [
  { to: "/score", label: "Score" },
  { to: "/rubrics", label: "Rubrics" },
  { to: "/calibration", label: "Calibration" },
];
