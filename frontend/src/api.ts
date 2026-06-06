import type { Organization, RunDetail, RunSummary } from "./types";

const API_BASE_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export async function fetchRuns(): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/runs`);
  if (!response.ok) {
    throw new Error("Could not load MergeFlow runs.");
  }
  return response.json();
}

export async function fetchOrganization(): Promise<Organization> {
  const response = await fetch(`${API_BASE_URL}/organization`);
  if (!response.ok) {
    throw new Error("Could not load organization.");
  }
  return response.json();
}

export async function fetchTeamRuns(teamId: string): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/teams/${encodeURIComponent(teamId)}/runs`);
  if (!response.ok) {
    throw new Error("Could not load team runs.");
  }
  return response.json();
}

export async function fetchServiceRuns(serviceId: string): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/services/${encodeURIComponent(serviceId)}/runs`);
  if (!response.ok) {
    throw new Error("Could not load service runs.");
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
