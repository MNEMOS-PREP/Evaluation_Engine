/**
 * M13 — Evaluation Engine · routes.
 *
 * Spec: plan_in_depth/M13_Evaluation_Engine.md §8 (UI specification)
 *
 * Flat, and keyed on `turn_id` rather than on an evaluation id. A re-score
 * appends a new evaluation and supersedes the old one, so an evaluation id is
 * a specific reading of an answer while the turn is the answer itself — and
 * "here is what I got on that question" is the link a student actually keeps.
 * `/v1/evaluations/{turn_id}` resolves to the surviving one.
 */

import { Route } from "react-router-dom";

import { CalibrationPage } from "./components/CalibrationPage";
import { DepsPage } from "./components/DepsPage";
import { DisputesPage } from "./components/DisputesPage";
import { OutboundPage } from "./components/OutboundPage";
import { OutboxPage } from "./components/OutboxPage";
import { RatersPage } from "./components/RatersPage";
import { RubricsPage } from "./components/RubricsPage";
import { ScoreBench } from "./components/ScoreBench";
import { TurnPage } from "./components/TurnPage";

export const m13Routes = (
  <Route key="m13">
    <Route path="/score" element={<ScoreBench />} />
    <Route path="/turns/:turnId" element={<TurnPage />} />
    <Route path="/turns/:turnId/outbound" element={<OutboundPage />} />
    <Route path="/rubrics" element={<RubricsPage />} />
    <Route path="/calibration" element={<CalibrationPage />} />
    <Route path="/disputes" element={<DisputesPage />} />
    <Route path="/raters" element={<RatersPage />} />
    <Route path="/outbox" element={<OutboxPage />} />
    <Route path="/deps" element={<DepsPage />} />
  </Route>
);
