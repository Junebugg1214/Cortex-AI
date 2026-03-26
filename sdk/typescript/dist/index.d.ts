export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface CortexClientOptions {
  apiKey?: string | null;
  namespace?: string | null;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface LogParams {
  limit?: number;
  ref?: string;
}

export interface PruneStatusParams {
  retentionDays?: number;
}

export interface PruneParams {
  dryRun?: boolean;
  retentionDays?: number;
}

export interface PruneAuditParams {
  limit?: number;
}

export interface IndexStatusParams {
  ref?: string;
}

export interface IndexRebuildParams {
  ref?: string;
  allRefs?: boolean;
}

export interface CreateBranchParams {
  name: string;
  fromRef?: string;
  switchBranch?: boolean;
  actor?: string;
  approve?: boolean;
}

export interface SwitchBranchParams {
  name: string;
  actor?: string;
  approve?: boolean;
}

export interface CheckoutParams {
  ref?: string;
  verify?: boolean;
}

export interface DiffParams {
  versionA: string;
  versionB: string;
}

export interface CommitParams {
  graph: JsonObject;
  message: string;
  source?: string;
  actor?: string;
  approve?: boolean;
}

export interface ReviewParams {
  against: string;
  graph?: JsonObject;
  ref?: string;
  failOn?: string;
}

export interface BlameParams {
  label?: string;
  nodeId?: string;
  graph?: JsonObject;
  ref?: string;
  source?: string;
  limit?: number;
}

export interface DetectConflictsParams {
  graph?: JsonObject;
  ref?: string;
  minSeverity?: number;
}

export interface ResolveConflictParams {
  conflictId: string;
  action: "accept-new" | "keep-old" | "merge" | "ignore";
  graph?: JsonObject;
  ref?: string;
}

export interface MergePreviewParams {
  otherRef: string;
  currentRef?: string;
  persist?: boolean;
}

export interface MergeResolveParams {
  conflictId: string;
  choose: "current" | "incoming";
}

export interface MergeCommitResolvedParams {
  message?: string;
  actor?: string;
  approve?: boolean;
}

export interface QueryCategoryParams {
  tag: string;
  graph?: JsonObject;
  ref?: string;
}

export interface QueryPathParams {
  fromLabel: string;
  toLabel: string;
  graph?: JsonObject;
  ref?: string;
}

export interface QueryRelatedParams {
  label: string;
  depth?: number;
  graph?: JsonObject;
  ref?: string;
}

export interface QuerySearchParams {
  query: string;
  graph?: JsonObject;
  ref?: string;
  limit?: number;
  minScore?: number;
}

export interface QueryDslParams {
  query: string;
  graph?: JsonObject;
  ref?: string;
}

export class CortexClient {
  constructor(baseUrl: string, options?: CortexClientOptions);
  health(): Promise<JsonObject>;
  meta(): Promise<JsonObject>;
  metrics(): Promise<JsonObject>;
  openapi(): Promise<JsonObject>;
  indexStatus(params?: IndexStatusParams): Promise<JsonObject>;
  indexRebuild(params?: IndexRebuildParams): Promise<JsonObject>;
  pruneStatus(params?: PruneStatusParams): Promise<JsonObject>;
  prune(params?: PruneParams): Promise<JsonObject>;
  pruneAudit(params?: PruneAuditParams): Promise<JsonObject>;
  log(params?: LogParams): Promise<JsonObject>;
  listBranches(): Promise<JsonObject>;
  createBranch(params: CreateBranchParams): Promise<JsonObject>;
  switchBranch(params: SwitchBranchParams): Promise<JsonObject>;
  checkout(params?: CheckoutParams): Promise<JsonObject>;
  diff(params: DiffParams): Promise<JsonObject>;
  commit(params: CommitParams): Promise<JsonObject>;
  review(params: ReviewParams): Promise<JsonObject>;
  blame(params?: BlameParams): Promise<JsonObject>;
  history(params?: BlameParams): Promise<JsonObject>;
  detectConflicts(params?: DetectConflictsParams): Promise<JsonObject>;
  resolveConflict(params: ResolveConflictParams): Promise<JsonObject>;
  mergePreview(params: MergePreviewParams): Promise<JsonObject>;
  mergeConflicts(): Promise<JsonObject>;
  mergeResolve(params: MergeResolveParams): Promise<JsonObject>;
  mergeCommitResolved(params?: MergeCommitResolvedParams): Promise<JsonObject>;
  mergeAbort(): Promise<JsonObject>;
  queryCategory(params: QueryCategoryParams): Promise<JsonObject>;
  queryPath(params: QueryPathParams): Promise<JsonObject>;
  queryRelated(params: QueryRelatedParams): Promise<JsonObject>;
  querySearch(params: QuerySearchParams): Promise<JsonObject>;
  queryDsl(params: QueryDslParams): Promise<JsonObject>;
  queryNl(params: QueryDslParams): Promise<JsonObject>;
}
