export interface Flag {
  check_id: string;
  label: string;
  severity: "high" | "medium" | "low";
  action: string;
  evidence_span: string;
  article_ref: string;
  article_ar?: string;
  article_en?: string;
  rationale: string;
  confidence?: number;
}

export interface Revision {
  clause_original: string;
  clause_revised: string;
  article_ref: string;
  rationale: string;
}

export interface DraftClause {
  text: string;
  article_ref: string;
  rationale: string;
}

export interface AgentInfo {
  domain: string;
  label: string;
  live: boolean;
  description: string;
}

export interface AuditResult {
  routing: {
    mode: string;
    classification: Array<{ domain: string; confidence: number }>;
    consulted: string[];
    stubbed: string[];
  };
  task: string;
  summary: string;
  flags_by_domain: Record<string, Flag[]>;
  specialist_results: Record<string, any>;
  trace: any[];
  status: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  files?: FileAttachment[];
  artifact?: Artifact | null;
  steps?: StepEvent[];
  timestamp: number;
}

export interface FileAttachment {
  name: string;
  size: number;
  type: string;
  file: File;
  text?: string;
}

export interface Artifact {
  type: "audit" | "revision" | "draft" | "contract";
  title: string;
  data: any;
  contractText?: string;
  file?: File;
}

export interface ReviseResult {
  domain: string;
  mode: string;
  summary: string;
  flags: Flag[];
  revisions: Revision[];
  revised_document?: string;
  status: string;
}

export interface DraftResult {
  domain: string;
  mode: string;
  summary: string;
  drafts: DraftClause[];
  drafted_document?: string;
  status: string;
}

export interface CostSummary {
  total_cost_usd: number;
  total_calls: number;
  total_tokens: number;
  by_model: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number; cost_usd: number }>;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  timestamp: number;
}

export interface StepEvent {
  action: string;
  detail: string;
  domain?: string;
  reason?: string;
}
