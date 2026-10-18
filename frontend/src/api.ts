import type { Organization, RunDetail, RunSummary } from "./types";

function resolveBackendUrl(): string {
  const envUrl = (import.meta.env.VITE_BACKEND_URL as string | undefined)?.trim();
  let url = envUrl || "https://mergeflow-ai-production.up.railway.app";
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    url = `https://${url}`;
  }
  return url.replace(/\/+$/, "");
}

const API_BASE_URL = resolveBackendUrl();

const DEFAULT_HEADERS: HeadersInit = {
  "ngrok-skip-browser-warning": "true",
};

export async function fetchRuns(): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/runs`, { headers: DEFAULT_HEADERS });
  if (!response.ok) {
    throw new Error("Could not load MergeFlow runs.");
  }
  return response.json();
}

export async function fetchOrganization(): Promise<Organization> {
  const response = await fetch(`${API_BASE_URL}/organization`, { headers: DEFAULT_HEADERS });
  if (!response.ok) {
    throw new Error("Could not load organization.");
  }
  return response.json();
}

export async function fetchTeamRuns(teamId: string): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/teams/${encodeURIComponent(teamId)}/runs`, { headers: DEFAULT_HEADERS });
  if (!response.ok) {
    throw new Error("Could not load team runs.");
  }
  return response.json();
}

export async function fetchServiceRuns(serviceId: string): Promise<RunSummary[]> {
  const response = await fetch(`${API_BASE_URL}/services/${encodeURIComponent(serviceId)}/runs`, { headers: DEFAULT_HEADERS });
  if (!response.ok) {
    throw new Error("Could not load service runs.");
  }
  return response.json();
}

export async function fetchRun(runId: string): Promise<RunDetail> {
  const response = await fetch(`${API_BASE_URL}/runs/${encodeURIComponent(runId)}`, { headers: DEFAULT_HEADERS });
  if (!response.ok) {
    throw new Error("Could not load MergeFlow run details.");
  }
  return response.json();
}
