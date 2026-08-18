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
