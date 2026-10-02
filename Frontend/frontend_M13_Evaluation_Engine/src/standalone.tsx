/**
 * M13 running alone on :5213.
 *
 * Same routes and components as the shell mounts — this file only supplies the
 * providers the shell would otherwise own, so that debugging this module in
 * isolation exercises the real code rather than a special build.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { setIdentityHeaders } from "@ai/core";

import { m13Routes } from "./routes";
import { AppShell } from "./ui/AppShell";
// One stylesheet, on purpose: theme.css imports @ai/core/styles.css itself so
// Tailwind sees a single entry graph and generates utilities from both token
// sets. Importing them separately here silently drops half the utilities.
import "./ui/theme.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});

// M13 alone on :5213 is the operator's console — the playground, the evidence
// drawer for any turn, the raters' queue — and M13's backend checks who is
// asking since 2026-10-02 (Platform_Core v0.11.0). So standalone, it says it
// is an operator. NOT in `routes.tsx`: inside Platform_Shell every module
// shares one page and one identity, and that identity is the student's — who
// may read their own evaluations and nobody else's, which is the point.
// Dev headers, honoured by the backend only under AI_AUTH_MODE=dev.
setIdentityHeaders({ "X-Role": "admin", "X-Candidate-Id": "m13-operator" });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            {m13Routes}
            <Route path="*" element={<Navigate to="/score" replace />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
