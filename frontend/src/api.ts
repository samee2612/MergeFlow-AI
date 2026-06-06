import type { RunDetail, RunSummary } from "./types";

const API_BASE_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export async function fetchRuns(): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/runs`);
  if (!response.ok) {
    throw new Error("Could not load MergeFlow runs.");
  }
  return response.json();
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) {
    throw new Error("Could not load MergeFlow run details.");
  }
  return response.json();
}
