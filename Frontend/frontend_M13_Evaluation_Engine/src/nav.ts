import type { NavItem } from "@ai/core";

/** Nav for M13 running standalone. The platform shell supplies its own. */
export const M13_NAV: NavItem[] = [
  { to: "/score", label: "Score" },
  { to: "/rubrics", label: "Rubrics" },
  { to: "/calibration", label: "Calibration" },
];
