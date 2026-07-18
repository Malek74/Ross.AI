import type { AgentInfo, AuditResult, CostSummary, DraftResult, ReviseResult, StepEvent } from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgents(): Promise<AgentInfo[]> {
  return request("/agents");
}

export async function extractText(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const result = await request<{ text: string }>("/extract", { method: "POST", body: form });
  return result.text;
}

export interface StreamCallbacks {
  onStep: (step: StepEvent) => void;
  onDone: (result: AuditResult) => void;
  onError: (error: string) => void;
}

async function consumeSSE(res: Response, callbacks: StreamCallbacks) {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  const processLines = (lines: string[]) => {
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ") && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          if (currentEvent === "step") callbacks.onStep(data);
          else if (currentEvent === "done") callbacks.onDone(data);
          else if (currentEvent === "error") callbacks.onError(data.detail);
        } catch { /* skip malformed JSON */ }
        currentEvent = "";
      } else if (line === "") {
        // empty line resets event per SSE spec
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    processLines(lines);
  }

  if (buffer.trim()) {
    processLines(buffer.split("\n"));
  }
}

export async function auditContractStream(
  file: File,
  mode: "auto" | "manual" = "auto",
  agents: string[] | undefined,
  lang: string,
  callbacks: StreamCallbacks,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  form.append("lang", lang);
  if (agents?.length) form.append("agents", JSON.stringify(agents));
  const res = await fetch(`${BASE}/audit/stream`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  await consumeSSE(res, callbacks);
}

export interface HistoryTurn {
  role: "user" | "assistant";
  content: string;
}

export async function chatWithParalegalStream(
  question: string,
  contractText: string | undefined,
  mode: "auto" | "manual",
  agents: string[] | undefined,
  lang: string,
  callbacks: StreamCallbacks,
  history?: HistoryTurn[],
): Promise<void> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      contract_text: contractText || null,
      history: history?.length ? history : null,
      mode,
      agents: agents?.length ? agents : null,
      lang,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  await consumeSSE(res, callbacks);
}

export async function auditContract(
  file: File,
  mode: "auto" | "manual" = "auto",
  agents?: string[],
  lang: string = "en",
): Promise<AuditResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  form.append("lang", lang);
  if (agents?.length) form.append("agents", JSON.stringify(agents));
  return request("/audit", { method: "POST", body: form });
}

export async function chatWithParalegal(
  question: string,
  contractText?: string,
  mode: "auto" | "manual" = "auto",
  agents?: string[],
  lang: string = "en",
): Promise<AuditResult> {
  return request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      contract_text: contractText || null,
      mode,
      agents: agents?.length ? agents : null,
      lang,
    }),
  });
}

export async function reviseContract(
  contractText: string,
  domain: string,
  flagIds?: string[],
  lang: string = "en",
): Promise<ReviseResult> {
  return request("/revise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contract_text: contractText,
      domain,
      flag_ids: flagIds?.length ? flagIds : null,
      lang,
    }),
  });
}

export async function draftContract(
  contractType: string,
  domain: string,
  requirements?: string,
  lang: string = "en",
): Promise<DraftResult> {
  return request("/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_type: contractType, domain, requirements: requirements || null, lang }),
  });
}

export async function highlightPdf(
  file: File,
  flags: { evidence_span: string; severity: string; index?: number }[],
): Promise<{ url: string; count: number }> {
  const form = new FormData();
  form.append("file", file);
  form.append("flags", JSON.stringify(flags));
  const res = await fetch(`${BASE}/highlight`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  const count = parseInt(res.headers.get("X-Highlight-Count") || "0", 10);
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), count };
}

export async function reviseContractStream(
  contractText: string,
  domain: string,
  flagIds: string[] | undefined,
  lang: string,
  callbacks: StreamCallbacks,
): Promise<void> {
  const res = await fetch(`${BASE}/revise/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_text: contractText, domain, flag_ids: flagIds?.length ? flagIds : null, lang }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  await consumeSSE(res, callbacks);
}

export async function draftContractStream(
  contractType: string,
  domain: string,
  requirements: string | undefined,
  lang: string,
  callbacks: StreamCallbacks,
): Promise<void> {
  const res = await fetch(`${BASE}/draft/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_type: contractType, domain, requirements: requirements || null, lang }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  await consumeSSE(res, callbacks);
}

export async function applyRevisionsPdf(
  contractText: string,
  revisions: { clause_original: string; clause_revised: string }[],
): Promise<{ url: string; applied: number }> {
  const res = await fetch(`${BASE}/apply-revisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_text: contractText, revisions }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  const applied = parseInt(res.headers.get("X-Applied-Count") || "0", 10);
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), applied };
}

export async function classifyIntent(
  text: string,
  hasContract: boolean,
  hasAudit: boolean,
): Promise<{ intent: "audit" | "revise" | "draft" | "chat" | null; domain: string | null }> {
  return request("/intent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, has_contract: hasContract, has_audit: hasAudit }),
  });
}

export async function fetchCost(): Promise<CostSummary> {
  return request("/cost");
}
