import { useState, useEffect, useCallback } from "react";
import { fetchAgents, auditContract, chatWithParalegal, reviseContract, draftContract } from "./api/client";
import type { AgentInfo, AuditResult, ChatMessage, FileAttachment, Artifact } from "./api/types";
import type { Lang } from "./i18n";
import { t, isRtl } from "./i18n";
import type { Theme } from "./context";
import { AppCtx } from "./context";
import TopBar from "./components/TopBar";
import ChatInput from "./components/ChatInput";
import MessageList from "./components/MessageList";
import ArtifactPanel from "./components/ArtifactPanel";
import Suggestions from "./components/Suggestions";

let msgId = 0;
const nextId = () => `msg-${++msgId}`;

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  const s = t(lang);

  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [routeMode, setRouteMode] = useState<"auto" | "manual">("auto");
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<FileAttachment[]>([]);
  const [contractText, setContractText] = useState("");
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("dir", isRtl(lang) ? "rtl" : "ltr");
    document.documentElement.setAttribute("lang", lang);
  }, [lang]);

  useEffect(() => {
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  const hasMessages = messages.length > 0;

  const addMessage = useCallback((role: "user" | "assistant", content: string, files?: FileAttachment[], art?: Artifact | null) => {
    const msg: ChatMessage = { id: nextId(), role, content, files, artifact: art, timestamp: Date.now() };
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const extractFileTexts = async (files: FileAttachment[]): Promise<FileAttachment[]> => {
    return Promise.all(
      files.map(async (f) => {
        if (f.type === "text/plain" && !f.text) {
          const text = await f.file.text();
          return { ...f, text };
        }
        return f;
      }),
    );
  };

  const handleSend = async (text: string, files: FileAttachment[]) => {
    if (loading) return;
    const enrichedFiles = await extractFileTexts(files);
    addMessage("user", text, enrichedFiles.length ? enrichedFiles : undefined);
    setLoading(true);

    try {
      const hasFiles = enrichedFiles.length > 0;
      const intent = detectIntent(text, hasFiles);

      if (intent === "audit" && hasFiles) {
        const results: AuditResult[] = [];
        for (const f of enrichedFiles) {
          if (f.text) setContractText(f.text);
          const result = await auditContract(
            f.file, routeMode,
            routeMode === "manual" && selectedAgents.length ? selectedAgents : undefined,
          );
          results.push(result);
          setAuditResult(result);
        }
        const merged = mergeAuditResults(results);
        const totalFlags = Object.values(merged.flags_by_domain).reduce((s, f) => s + f.length, 0);
        const art: Artifact = {
          type: "audit", title: `Audit Report — ${totalFlags} flags`,
          data: merged, contractText: contractText || enrichedFiles[0]?.text,
        };
        setArtifact(art);
        addMessage("assistant", merged.summary, undefined, art);
      } else if (intent === "revise") {
        const domain = selectedAgents[0] || Object.keys(auditResult?.flags_by_domain || {})[0] || "civil";
        const ct = contractText || enrichedFiles[0]?.text || "";
        const result = await reviseContract(ct, domain);
        const art: Artifact = { type: "revision", title: "Revised Contract", data: result, contractText: ct };
        setArtifact(art);
        addMessage("assistant", result.summary, undefined, art);
      } else if (intent === "draft") {
        const domain = selectedAgents[0] || "civil";
        const contractType = extractContractType(text);
        const result = await draftContract(contractType, domain, text);
        const art: Artifact = { type: "draft", title: `Draft: ${contractType}`, data: result };
        setArtifact(art);
        addMessage("assistant", result.summary, undefined, art);
      } else {
        const ct = contractText || enrichedFiles.map((f) => f.text).filter(Boolean).join("\n\n") || "";
        if (ct && !contractText) setContractText(ct);
        const result = await chatWithParalegal(
          text, ct || undefined, routeMode,
          routeMode === "manual" && selectedAgents.length ? selectedAgents : undefined,
        );
        const hasFlags = Object.values(result.flags_by_domain || {}).some((f) => f.length > 0);
        const art: Artifact | null = hasFlags
          ? { type: "audit", title: "Legal Analysis", data: result, contractText: ct }
          : null;
        if (art) setArtifact(art);
        addMessage("assistant", result.summary, undefined, art);
      }
    } catch (err: any) {
      addMessage("assistant", `${s.errorPrefix} ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSuggestion = (text: string) => {
    handleSend(text, uploadedFiles);
    setUploadedFiles([]);
  };

  return (
    <AppCtx.Provider value={{ lang, theme, s }}>
      <div className="h-screen flex" style={{ background: "var(--bg)" }}>
        {/* Main chat area */}
        <div className={`flex-1 flex flex-col min-w-0 transition-all duration-300`}>
          <TopBar lang={lang} theme={theme} onLangChange={setLang} onThemeChange={setTheme} />

          <div className="flex-1 flex flex-col min-h-0">
            {!hasMessages ? (
              <div className="flex-1 flex flex-col items-center justify-center px-4">
                <div style={{ width: "100%", maxWidth: "48rem" }}>
                  <h1 className="text-3xl font-normal mb-8 text-center" style={{ color: "var(--text)" }}>
                    {s.heading}
                  </h1>
                  <ChatInput onSend={handleSend} loading={loading} files={uploadedFiles} onFilesChange={setUploadedFiles}
                    agents={agents} routeMode={routeMode} selectedAgents={selectedAgents}
                    onRouteChange={setRouteMode} onAgentsChange={setSelectedAgents} />
                  <Suggestions hasFiles={uploadedFiles.length > 0} hasContract={!!contractText}
                    hasAudit={!!auditResult} onSelect={handleSuggestion} />
                </div>
              </div>
            ) : (
              <>
                <div className="flex-1 w-full overflow-y-auto scrollbar-thin">
                  <MessageList messages={messages} loading={loading} onArtifactClick={setArtifact} />
                </div>
                <div className="px-4 pb-4 shrink-0" style={{ width: "100%", maxWidth: "48rem", margin: "0 auto" }}>
                  <ChatInput onSend={handleSend} loading={loading} files={uploadedFiles} onFilesChange={setUploadedFiles}
                    agents={agents} routeMode={routeMode} selectedAgents={selectedAgents}
                    onRouteChange={setRouteMode} onAgentsChange={setSelectedAgents} />
                </div>
              </>
            )}
          </div>
        </div>

        {artifact && <ArtifactPanel artifact={artifact} onClose={() => setArtifact(null)} />}
      </div>
    </AppCtx.Provider>
  );
}

function detectIntent(text: string, hasFiles: boolean): "audit" | "revise" | "draft" | "chat" {
  const lower = text.toLowerCase();
  if (hasFiles && (lower.includes("audit") || lower.includes("review") || lower.includes("check") || lower.includes("analyze") || lower.includes("scan") || !text.trim()))
    return "audit";
  if (lower.includes("revise") || lower.includes("fix") || lower.includes("rewrite") || lower.includes("correct"))
    return "revise";
  if (lower.includes("draft") || lower.includes("create") || lower.includes("generate") || lower.includes("write a contract"))
    return "draft";
  if (hasFiles) return "audit";
  return "chat";
}

function extractContractType(text: string): string {
  const patterns = [/draft\s+(?:a\s+)?(\w+(?:\s+\w+)?)\s+contract/i, /create\s+(?:a\s+)?(\w+(?:\s+\w+)?)\s+contract/i, /(\w+)\s+contract/i];
  for (const p of patterns) { const m = text.match(p); if (m) return m[1]; }
  return "general";
}

function mergeAuditResults(results: AuditResult[]): AuditResult {
  if (results.length === 1) return results[0];
  const merged: AuditResult = {
    ...results[0], flags_by_domain: {},
    routing: { ...results[0].routing, consulted: [], stubbed: [] },
  };
  for (const r of results) {
    for (const [domain, flags] of Object.entries(r.flags_by_domain)) {
      merged.flags_by_domain[domain] = [...(merged.flags_by_domain[domain] || []), ...flags];
    }
    merged.routing.consulted.push(...r.routing.consulted.filter((d) => !merged.routing.consulted.includes(d)));
    merged.routing.stubbed.push(...r.routing.stubbed.filter((d) => !merged.routing.stubbed.includes(d)));
  }
  merged.summary = results.map((r) => r.summary).join("\n\n");
  return merged;
}
