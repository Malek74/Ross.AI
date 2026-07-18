import { useState, useEffect, useCallback } from "react";
import { fetchAgents, auditContractStream, chatWithParalegalStream, reviseContractStream, draftContractStream, extractText, classifyIntent } from "./api/client";
import type { AgentInfo, AuditResult, ChatMessage, FileAttachment, Artifact, Conversation, StepEvent } from "./api/types";
import type { Lang } from "./i18n";
import { t, isRtl } from "./i18n";
import type { Theme } from "./context";
import { AppCtx } from "./context";
import TopBar from "./components/TopBar";
import ChatInput from "./components/ChatInput";
import MessageList from "./components/MessageList";
import ArtifactPanel from "./components/ArtifactPanel";
import Suggestions from "./components/Suggestions";
import HistorySidebar from "./components/HistorySidebar";

let msgId = 0;
const nextId = () => `msg-${++msgId}`;

const STORAGE_KEY = "rossai-conversations";

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveConversations(convos: Conversation[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(convos));
}

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<Theme>("dark");
  const s = t(lang);

  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [routeMode, setRouteMode] = useState<"auto" | "manual">("auto");
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [liveSteps, setLiveSteps] = useState<StepEvent[]>([]);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [uploadedFiles, setUploadedFiles] = useState<FileAttachment[]>([]);
  const [contractText, setContractText] = useState("");
  const [auditResult, setAuditResult] = useState<AuditResult | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeConvoId, setActiveConvoId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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

  useEffect(() => {
    if (messages.length > 0) {
      const title = messages[0].content.slice(0, 50) || "New conversation";
      const convo: Conversation = {
        id: activeConvoId || `conv-${Date.now()}`,
        title,
        messages,
        timestamp: Date.now(),
      };
      if (!activeConvoId) setActiveConvoId(convo.id);
      setConversations((prev) => {
        const existing = prev.findIndex((c) => c.id === convo.id);
        const updated = existing >= 0
          ? prev.map((c) => (c.id === convo.id ? convo : c))
          : [convo, ...prev];
        saveConversations(updated);
        return updated;
      });
    }
  }, [messages]);

  const hasMessages = messages.length > 0;

  const addMessage = useCallback((role: "user" | "assistant", content: string, files?: FileAttachment[], art?: Artifact | null, steps?: StepEvent[]) => {
    const msg: ChatMessage = { id: nextId(), role, content, files, artifact: art, steps, timestamp: Date.now() };
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const startNewChat = () => {
    setMessages([]);
    setActiveConvoId(null);
    setArtifact(null);
    setContractText("");
    setAuditResult(null);
    setUploadedFiles([]);
  };

  const loadConversation = (convo: Conversation) => {
    setMessages(convo.messages);
    setActiveConvoId(convo.id);
    setArtifact(null);
    setSidebarOpen(false);
  };

  const deleteConversation = (id: string) => {
    setConversations((prev) => {
      const updated = prev.filter((c) => c.id !== id);
      saveConversations(updated);
      return updated;
    });
    if (activeConvoId === id) startNewChat();
  };

  const clearAllConversations = () => {
    saveConversations([]);
    setConversations([]);
    startNewChat();
  };

  const extractFileTexts = async (files: FileAttachment[]): Promise<FileAttachment[]> => {
    return Promise.all(
      files.map(async (f) => {
        if (f.text) return f;
        if (f.type === "text/plain") {
          const text = await f.file.text();
          return { ...f, text };
        }
        const text = await extractText(f.file);
        return { ...f, text };
      }),
    );
  };

  const friendlyError = (msg: string): string => {
    console.error("[Ross.AI error]", msg);
    const lower = msg.toLowerCase();
    if (lower.includes("credit limit") || lower.includes("key limit") || (lower.includes("limit") && lower.includes("exceeded")))
      return s.errorCredits;
    if (lower.includes("rate limit") || lower.includes("rate-limited") || lower.includes("overloaded") || msg.includes("429"))
      return s.errorRateLimit;
    if (msg.includes("401") || lower.includes("unauthorized") || lower.includes("invalid") && lower.includes("key"))
      return s.errorApiKey;
    if (lower.includes("failed to fetch") || lower.includes("networkerror") || lower.includes("econnrefused"))
      return s.errorNetwork;
    return `${s.errorPrefix} ${msg}`;
  };

  const handleStreamResult = (result: AuditResult, enrichedFiles: FileAttachment[], collectedSteps: StepEvent[]) => {
    const totalFlags = Object.values(result.flags_by_domain || {}).reduce((sum, f) => sum + f.length, 0);
    const ct = contractText || enrichedFiles[0]?.text || "";
    const title = totalFlags > 0
      ? `${s.report} — ${totalFlags} ${totalFlags !== 1 ? s.flags : s.flag}`
      : s.report;
    const srcFile = enrichedFiles[0]?.file;
    const art: Artifact = {
      type: "audit", title, data: result, contractText: ct,
      file: srcFile && srcFile.type === "application/pdf" ? srcFile : undefined,
    };
    setArtifact(art);
    setAuditResult(result);
    addMessage("assistant", result.summary, undefined, art, collectedSteps);
  };

  const handleSend = async (text: string, files: FileAttachment[]) => {
    if (loading) return;
    const enrichedFiles = await extractFileTexts(files);
    addMessage("user", text, enrichedFiles.length ? enrichedFiles : undefined);
    setLoading(true);
    setLiveSteps([]);

    try {
      const hasFiles = enrichedFiles.length > 0;
      let intent = detectIntent(text, hasFiles);
      let llmDomain: string | null = null;
      try {
        const r = await classifyIntent(text, hasFiles || !!contractText, !!auditResult);
        if (r.intent) { intent = r.intent; llmDomain = r.domain; }
      } catch { /* offline or classifier error — keyword fallback already applied */ }
      const agentsList = routeMode === "manual" && selectedAgents.length ? selectedAgents : undefined;
      const collectedSteps: StepEvent[] = [];

      if (intent === "audit" && hasFiles) {
        for (const f of enrichedFiles) {
          if (f.text) setContractText(f.text);
          let gotResponse = false;
          await auditContractStream(f.file, routeMode, agentsList, lang, {
            onStep: (step) => { collectedSteps.push(step); setLiveSteps([...collectedSteps]); },
            onDone: (result) => { gotResponse = true; handleStreamResult(result, enrichedFiles, collectedSteps); },
            onError: (err) => { gotResponse = true; addMessage("assistant", friendlyError(err)); },
          });
          if (!gotResponse) {
            addMessage("assistant", "No response received from the server.");
          }
        }
      } else if (intent === "revise" && (contractText || enrichedFiles[0]?.text)) {
        const domain = selectedAgents[0] || llmDomain || Object.keys(auditResult?.flags_by_domain || {})[0] || detectDomain(text + " " + (contractText || "").slice(0, 500));
        const ct = contractText || enrichedFiles[0]?.text || "";
        await reviseContractStream(ct, domain, undefined, lang, {
          onStep: (step) => { collectedSteps.push(step); setLiveSteps([...collectedSteps]); },
          onDone: (result) => {
            const art: Artifact = { type: "revision", title: s.revised, data: result, contractText: ct };
            setArtifact(art);
            // Keep the revised contract as the session context so follow-up
            // questions and further revisions operate on the updated text.
            let revised = ct;
            for (const rev of result.revisions || []) {
              if (rev.clause_original && rev.clause_revised && revised.includes(rev.clause_original)) {
                revised = revised.replace(rev.clause_original, rev.clause_revised);
              }
            }
            if (revised !== ct) setContractText(revised);
            addMessage("assistant", result.summary, undefined, art, collectedSteps);
          },
          onError: (err) => addMessage("assistant", friendlyError(err)),
        });
      } else if (intent === "draft") {
        const domain = selectedAgents[0] || llmDomain || detectDomain(text);
        const contractType = extractContractType(text);
        await draftContractStream(contractType, domain, text, lang, {
          onStep: (step) => { collectedSteps.push(step); setLiveSteps([...collectedSteps]); },
          onDone: (result) => {
            const art: Artifact = { type: "draft", title: `${s.draftContract}: ${contractType}`, data: result };
            setArtifact(art);
            // The drafted contract becomes the session contract so the user can
            // ask follow-ups about it, audit it, or revise it next.
            if (result.document) setContractText(result.document);
            addMessage("assistant", result.summary, undefined, art, collectedSteps);
          },
          onError: (err) => addMessage("assistant", friendlyError(err)),
        });
      } else {
        const fileTexts = enrichedFiles.map((f) => f.text).filter(Boolean).join("\n\n");
        const ct = contractText || fileTexts || "";
        if (ct && !contractText) setContractText(ct);
        const history = messages.slice(-8).map((m) => ({ role: m.role, content: m.content.slice(0, 1500) }));
        if (auditResult) {
          const flagDigest = Object.entries(auditResult.flags_by_domain || {})
            .flatMap(([domain, flags]) => flags.map((f) => `[${domain}/${f.severity}] ${f.label} (${f.article_ref}): ${f.rationale}`))
            .join("\n");
          if (flagDigest) history.unshift({ role: "assistant", content: `Previous audit findings:\n${flagDigest}`.slice(0, 3000) });
        }
        let gotResponse = false;
        await chatWithParalegalStream(text, ct || undefined, routeMode, agentsList, lang, {
          onStep: (step) => { collectedSteps.push(step); setLiveSteps([...collectedSteps]); },
          onDone: (result) => {
            gotResponse = true;
            const totalFlags = Object.values(result.flags_by_domain || {}).reduce((sum, f) => sum + f.length, 0);
            if (totalFlags > 0) {
              handleStreamResult(result, enrichedFiles, collectedSteps);
            } else {
              addMessage("assistant", result.summary || "No response.", undefined, undefined, collectedSteps);
            }
          },
          onError: (err) => { gotResponse = true; addMessage("assistant", friendlyError(err)); },
        }, history);
        if (!gotResponse) {
          addMessage("assistant", "No response received from the server.");
        }
      }
    } catch (err: any) {
      addMessage("assistant", friendlyError(err.message || ""));
    } finally {
      setLoading(false);
      setLiveSteps([]);
    }
  };

  const handleSuggestion = (text: string) => {
    handleSend(text, uploadedFiles);
    setUploadedFiles([]);
  };

  return (
    <AppCtx.Provider value={{ lang, theme, s }}>
      <div className="h-screen w-full flex" style={{ background: "var(--bg)" }}>
        <HistorySidebar
          conversations={conversations}
          activeId={activeConvoId}
          open={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
          onSelect={loadConversation}
          onDelete={deleteConversation}
          onNewChat={startNewChat}
          onClearAll={clearAllConversations}
        />

        <div className={`flex-1 flex flex-col min-w-0 transition-all duration-300`}>
          <TopBar lang={lang} theme={theme} onLangChange={setLang} onThemeChange={setTheme}
            onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} onNewChat={startNewChat} />

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
                  <MessageList messages={messages} loading={loading} steps={liveSteps} onArtifactClick={setArtifact} />
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

function detectDomain(text: string): string {
  const lower = text.toLowerCase();
  if (/employ|labou?r|salary|wage|worker|dismiss|عمل|موظف|أجر|عامل|فصل/.test(lower)) return "labour";
  if (/commercial|company|trade|partnership|تجاري|شركة|تجارة/.test(lower)) return "commercial";
  return "civil";
}

function detectIntent(text: string, hasFiles: boolean): "audit" | "revise" | "draft" | "chat" {
  const lower = text.toLowerCase();
  const auditWords = ["audit", "review", "check", "analyze", "scan", "فحص", "مراجعة", "تحليل"];
  const reviseWords = ["revise", "fix", "rewrite", "correct", "changes", "amend", "adjust", "enhance", "improve", "modify", "update", "apply the", "تعديل", "إصلاح", "تصحيح", "التغييرات", "تحسين", "حسّن", "عدّل"];
  const draftWords = ["draft", "create", "generate", "write a contract", "صياغة", "إنشاء"];

  if (auditWords.some((w) => lower.includes(w))) return "audit";
  if (reviseWords.some((w) => lower.includes(w))) return "revise";
  if (draftWords.some((w) => lower.includes(w))) return "draft";
  if (hasFiles && !text.trim()) return "audit";
  return "chat";
}

function extractContractType(text: string): string {
  const patterns = [/draft\s+(?:a\s+)?(\w+(?:\s+\w+)?)\s+contract/i, /create\s+(?:a\s+)?(\w+(?:\s+\w+)?)\s+contract/i, /(\w+)\s+contract/i];
  for (const p of patterns) { const m = text.match(p); if (m) return m[1]; }
  // Arabic: «عقد بيع سيارة», «صياغة عقد ايجار …» → keep the phrase after عقد
  const ar = text.match(/عقد\s+((?:[؀-ۿ]+\s*){1,4})/);
  if (ar) return `عقد ${ar[1].trim()}`;
  if (/[؀-ۿ]/.test(text)) return text.trim().slice(0, 50);
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
