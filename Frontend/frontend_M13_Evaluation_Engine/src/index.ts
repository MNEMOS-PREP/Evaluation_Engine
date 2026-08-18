/**
 * M13 — Evaluation Engine · public surface.
 *
 * Anything not exported here is private to this module. `Judgement` and
 * `Transcript` are exported because M19 renders the same evidence in a report
 * and M17 renders the same spans on a fused timeline — and two copies of the
 * component that decides whether a number may be shown is exactly how the
 * display gate stops being true in whichever copy fell behind.
 */

export { m13Routes } from "./routes";
export { M13_NAV } from "./nav";
export { AppShell } from "./ui/AppShell";
export { Judgement, GATE_NOTE } from "./components/Judgement";
export { Transcript, segment } from "./components/Transcript";
export {
  useCalibration,
  useEvaluation,
  useEvidence,
  useOutbound,
  useRubric,
  useRubrics,
} from "./api";
export type {
  DrawerArtifact,
  DrawerDimension,
  EvidenceDrawer,
  Rubric,
  TurnEvaluation,
} from "./types";
