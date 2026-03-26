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

export interface LookupNodesParams {
  nodeId?: string;
  canonicalId?: string;
  label?: string;
  ref?: string;
  limit?: number;
}

export interface GetNodeParams {
  nodeId: string;
  ref?: string;
}

export interface UpsertNodeParams {
  node: JsonObject;
  ref?: string;
  message?: string;
  source?: string;
  actor?: string;
  approve?: boolean;
  recordClaim?: boolean;
  claimSource?: string;
  claimMethod?: string;
  claimMetadata?: JsonObject;
}

export interface DeleteNodeParams {
  nodeId?: string;
  canonicalId?: string;
  label?: string;
  ref?: string;
  message?: string;
  source?: string;
  actor?: string;
  approve?: boolean;
  recordClaim?: boolean;
  claimSource?: string;
  claimMethod?: string;
  claimMetadata?: JsonObject;
}

export interface LookupEdgesParams {
  edgeId?: string;
  sourceId?: string;
  targetId?: string;
  relation?: string;
  ref?: string;
  limit?: number;
}

export interface GetEdgeParams {
  edgeId: string;
  ref?: string;
}

export interface UpsertEdgeParams {
  edge: JsonObject;
  ref?: string;
  message?: string;
  source?: string;
  actor?: string;
  approve?: boolean;
}

export interface DeleteEdgeParams {
  edgeId?: string;
  sourceId?: string;
  targetId?: string;
  relation?: string;
  ref?: string;
  message?: string;
  source?: string;
  actor?: string;
  approve?: boolean;
}

export interface ListClaimsParams {
  claimId?: string;
  nodeId?: string;
  canonicalId?: string;
  label?: string;
  source?: string;
  ref?: string;
  versionRef?: string;
  op?: string;
  limit?: number;
}

export interface AssertClaimParams {
  node?: JsonObject;
  nodeId?: string;
  canonicalId?: string;
  label?: string;
  ref?: string;
  materialize?: boolean;
  message?: string;
  source?: string;
  method?: string;
  actor?: string;
  approve?: boolean;
  metadata?: JsonObject;
}

export interface RetractClaimParams {
  claimId?: string;
  nodeId?: string;
  canonicalId?: string;
  label?: string;
  ref?: string;
  materialize?: boolean;
  message?: string;
  actor?: string;
  approve?: boolean;
  metadata?: JsonObject;
}

export interface MemoryBatchParams {
  operations: JsonObject[];
  ref?: string;
  message?: string;
  source?: string;
  actor?: string;
  approve?: boolean;
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
  lookupNodes(params?: LookupNodesParams): Promise<JsonObject>;
  getNode(params: GetNodeParams): Promise<JsonObject>;
  upsertNode(params: UpsertNodeParams): Promise<JsonObject>;
  deleteNode(params?: DeleteNodeParams): Promise<JsonObject>;
  lookupEdges(params?: LookupEdgesParams): Promise<JsonObject>;
  getEdge(params: GetEdgeParams): Promise<JsonObject>;
  upsertEdge(params: UpsertEdgeParams): Promise<JsonObject>;
  deleteEdge(params?: DeleteEdgeParams): Promise<JsonObject>;
  listClaims(params?: ListClaimsParams): Promise<JsonObject>;
  assertClaim(params?: AssertClaimParams): Promise<JsonObject>;
  retractClaim(params?: RetractClaimParams): Promise<JsonObject>;
  memoryBatch(params: MemoryBatchParams): Promise<JsonObject>;
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
