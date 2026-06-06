export type RunStatus = "SUCCESS" | "NEEDS_ATTENTION" | "FAILED" | "RUNNING";

export type RunSummary = {
  id: string;
  prNumber: number | string;
  prTitle: string;
  repository: string;
  status: RunStatus;
  timestamp: string;
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
