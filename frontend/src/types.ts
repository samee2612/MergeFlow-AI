export type RunStatus =
  | "SUCCESS"
  | "NEEDS_ATTENTION"
  | "FAILED"
  | "RUNNING"
  | "TRACKED_ONLY"
  | "IGNORED";

export type ChangeScope = "api" | "frontend" | "database" | "infra" | "mixed";
export type ChangeAction = "generate_api_artifacts" | "track_only";

export type RunSummary = {
  id: string;
  prNumber: number | string;
  prTitle: string;
  repository: string;
  author?: string;
  headBranch?: string;
  baseBranch?: string;
  status: RunStatus;
  timestamp: string;
  teamId: string;
  teamName: string;
  serviceId: string;
  serviceName: string;
  changeScope?: ChangeScope;
  action?: ChangeAction;
};

export type PipelineStatus = {
  backendDetection: boolean;
  classification: boolean;
  testCaseGeneration: boolean;
  openapiGeneration: boolean;
  postmanGeneration: boolean;
  notionUpdate: boolean;
  emailSent: boolean;
};

export type ArtifactLink = {
  label: string;
  url: string;
};

export type ApiEndpoint = {
  method: string;
  path: string;
  requestFields: string[];
  responseCodes: number[];
};

export type GeneratedTestCase = {
  name: string;
  expected: string;
};

export type RunDetail = RunSummary & {
  pipelineStatus: PipelineStatus;
  classification: {
    changeTypes: string[];
    summary: string;
  };
  artifacts: Record<string, ArtifactLink>;
  apiOverview: ApiEndpoint[];
  testCases: GeneratedTestCase[];
};

export type Service = {
  id: string;
  name: string;
  repository: string;
  description: string;
  owner: string;
};

export type Team = {
  id: string;
  name: string;
  description: string;
  services: Service[];
};

export type Organization = {
  id: string;
  name: string;
  description: string;
  teams: Team[];
};
