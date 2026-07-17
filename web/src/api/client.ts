import type { AgentInfo, AuditResult, CostSummary, DraftResult, ReviseResult } from "./types";

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

export async function auditContract(
  file: File,
  mode: "auto" | "manual" = "auto",
  agents?: string[],
): Promise<AuditResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  if (agents?.length) form.append("agents", JSON.stringify(agents));
  return request("/audit", { method: "POST", body: form });
}

export async function chatWithParalegal(
  question: string,
  contractText?: string,
  mode: "auto" | "manual" = "auto",
  agents?: string[],
): Promise<AuditResult> {
  return request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      contract_text: contractText || null,
      mode,
      agents: agents?.length ? agents : null,
    }),
  });
}

export async function reviseContract(
  contractText: string,
  domain: string,
  flagIds?: string[],
): Promise<ReviseResult> {
  return request("/revise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contract_text: contractText,
      domain,
      flag_ids: flagIds?.length ? flagIds : null,
    }),
  });
}

export async function draftContract(
  contractType: string,
  domain: string,
  requirements?: string,
): Promise<DraftResult> {
  return request("/draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contract_type: contractType, domain, requirements: requirements || null }),
  });
}

export async function fetchCost(): Promise<CostSummary> {
  return request("/cost");
}
