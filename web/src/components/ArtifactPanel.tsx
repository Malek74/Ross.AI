import { useState, useMemo } from "react";
import { X, AlertTriangle, AlertCircle, Info, ChevronDown, ChevronRight, FileText } from "lucide-react";
import type { Artifact, Flag, Revision, DraftClause } from "../api/types";
import { useApp } from "../context";

interface Props {
  artifact: Artifact;
  onClose: () => void;
}

type PanelTab = "report" | "contract";

export default function ArtifactPanel({ artifact, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<PanelTab>("report");
  const [activeFlag, setActiveFlag] = useState<Flag | null>(null);
  const { s } = useApp();
  const hasContract = !!artifact.contractText;

  return (
    <div className="w-[480px] shrink-0 flex flex-col animate-fade-in"
      style={{ borderLeft: "1px solid var(--border)", background: "var(--bg-secondary)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2 min-w-0">
          <FileText size={16} className="text-indigo-400 shrink-0" />
          <span className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>{artifact.title}</span>
        </div>
        <button onClick={onClose} className="p-1 rounded-md transition-colors"
          style={{ color: "var(--text-muted)" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-input)"; e.currentTarget.style.color = "var(--text)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; }}>
          <X size={18} />
        </button>
      </div>

      {hasContract && (
        <div className="flex shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          {(["report", "contract"] as PanelTab[]).map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                activeTab === tab ? "border-indigo-500" : "border-transparent"
              }`}
              style={{ color: activeTab === tab ? "var(--text)" : "var(--text-muted)" }}>
              {tab === "report" ? s.report : s.contract}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {activeTab === "report" ? (
          <ReportContent artifact={artifact} activeFlag={activeFlag}
            onFlagClick={(f) => { setActiveFlag(f); if (hasContract) setActiveTab("contract"); }} />
        ) : (
          <ContractContent text={artifact.contractText || ""} activeFlag={activeFlag} />
        )}
      </div>
    </div>
  );
}

function ContractContent({ text, activeFlag }: { text: string; activeFlag: Flag | null }) {
  const highlighted = useMemo(() => {
    if (!activeFlag?.evidence_span || !text) return null;
    const span = activeFlag.evidence_span;
    const idx = text.indexOf(span);
    if (idx === -1) return null;
    return { before: text.slice(0, idx), match: span, after: text.slice(idx + span.length) };
  }, [text, activeFlag]);

  return (
    <div className="p-4 text-sm whitespace-pre-wrap font-mono leading-relaxed" style={{ color: "var(--text-secondary)" }}>
      {highlighted ? (
        <>{highlighted.before}<mark className="clause-highlight">{highlighted.match}</mark>{highlighted.after}</>
      ) : text}
    </div>
  );
}

function ReportContent({ artifact, activeFlag, onFlagClick }: { artifact: Artifact; activeFlag: Flag | null; onFlagClick: (f: Flag) => void }) {
  if (artifact.type === "audit") return <AuditReport data={artifact.data} activeFlag={activeFlag} onFlagClick={onFlagClick} />;
  if (artifact.type === "revision") return <RevisionReport data={artifact.data} />;
  if (artifact.type === "draft") return <DraftReport data={artifact.data} />;
  return <p className="p-4 text-sm" style={{ color: "var(--text-muted)" }}>No report data</p>;
}

function AuditReport({ data, activeFlag, onFlagClick }: { data: any; activeFlag: Flag | null; onFlagClick: (f: Flag) => void }) {
  const { s } = useApp();
  const flagsByDomain: Record<string, Flag[]> = data.flags_by_domain || {};
  const consulted: string[] = data.routing?.consulted || [];

  return (
    <div className="p-4 space-y-4">
      {consulted.length > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{s.consulted}: {consulted.join(", ")}</div>
      )}
      {Object.entries(flagsByDomain).map(([domain, flags]) => (
        <div key={domain}>
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2 flex items-center gap-2"
            style={{ color: "var(--text-secondary)" }}>
            {domain}
            <span className="font-normal normal-case tracking-normal" style={{ color: "var(--text-muted)" }}>
              {flags.length} {flags.length !== 1 ? s.flags : s.flag}
            </span>
          </h3>
          <div className="space-y-2">
            {flags.map((flag, i) => (
              <FlagCard key={flag.check_id || i} flag={flag} isActive={activeFlag === flag} onClick={() => onFlagClick(flag)} />
            ))}
          </div>
        </div>
      ))}
      {Object.keys(flagsByDomain).length === 0 && (
        <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>{s.noFlags}</p>
      )}
    </div>
  );
}

function FlagCard({ flag, isActive, onClick }: { flag: Flag; isActive: boolean; onClick: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const { s } = useApp();
  const sev = flag.severity || "medium";
  const icons = { high: AlertTriangle, medium: AlertCircle, low: Info };
  const Icon = icons[sev] || AlertCircle;

  return (
    <div onClick={onClick}
      className={`rounded-lg p-3 cursor-pointer transition-all ${isActive ? "ring-1 ring-indigo-500" : ""}`}
      style={{
        background: `var(--severity-${sev === "medium" ? "med" : sev}-bg)`,
        border: `1px solid var(--severity-${sev === "medium" ? "med" : sev}-border)`,
      }}>
      <div className="flex items-start gap-2">
        <Icon size={15} className="mt-0.5 shrink-0" style={{ color: `var(--severity-${sev === "medium" ? "med" : sev}-text)` }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
              style={{ background: `var(--severity-${sev === "medium" ? "med" : sev}-badge)`, color: `var(--severity-${sev === "medium" ? "med" : sev}-text)` }}>
              {sev.toUpperCase()}
            </span>
            <span className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>{flag.article_ref}</span>
          </div>
          <p className="text-sm font-medium mb-0.5" style={{ color: "var(--text)" }}>{flag.label}</p>
          <p className="text-xs line-clamp-2" style={{ color: "var(--text-secondary)" }}>{flag.rationale}</p>

          <button onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
            className="flex items-center gap-1 mt-2 text-xs text-indigo-400 hover:text-indigo-300">
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {expanded ? s.hideDetails : s.showDetails}
          </button>

          {expanded && (
            <div className="mt-2 space-y-2 text-xs">
              {flag.evidence_span && (
                <div>
                  <span className="font-medium" style={{ color: "var(--text-muted)" }}>{s.citedQuote}:</span>
                  <p className="mt-1 rounded p-2 italic"
                    style={{ color: "var(--text-secondary)", background: "var(--bg-input)", border: "1px solid var(--border)" }}>
                    "{flag.evidence_span}"
                  </p>
                </div>
              )}
              {flag.article_ar && (
                <div dir="rtl" className="text-right">
                  <span className="font-medium" style={{ color: "var(--text-muted)" }}>{s.articleAr}:</span>
                  <p className="mt-1 rounded p-2"
                    style={{ color: "var(--text-secondary)", background: "var(--bg-input)", border: "1px solid var(--border)" }}>
                    {flag.article_ar}
                  </p>
                </div>
              )}
              {flag.article_en && (
                <div>
                  <span className="font-medium" style={{ color: "var(--text-muted)" }}>{s.article}:</span>
                  <p className="mt-1 rounded p-2"
                    style={{ color: "var(--text-secondary)", background: "var(--bg-input)", border: "1px solid var(--border)" }}>
                    {flag.article_en}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RevisionReport({ data }: { data: any }) {
  const { s } = useApp();
  const revisions: Revision[] = data.revisions || [];
  return (
    <div className="p-4 space-y-3">
      {revisions.map((rev, i) => (
        <div key={i} className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}>
          <div className="grid grid-cols-2" style={{ borderBottom: "none" }}>
            <div className="p-3" style={{ borderRight: "1px solid var(--border)" }}>
              <div className="text-[10px] font-semibold uppercase mb-1" style={{ color: "var(--severity-high-text)" }}>{s.original}</div>
              <p className="text-xs whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>{rev.clause_original}</p>
            </div>
            <div className="p-3">
              <div className="text-[10px] font-semibold uppercase mb-1 text-green-400">{s.revised}</div>
              <p className="text-xs whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>{rev.clause_revised}</p>
            </div>
          </div>
          <div className="px-3 py-2 text-[11px]"
            style={{ background: "var(--bg-input)", borderTop: "1px solid var(--border)", color: "var(--text-muted)" }}>
            <span className="text-indigo-400">{rev.article_ref}</span> — {rev.rationale}
          </div>
        </div>
      ))}
      {revisions.length === 0 && <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>No revisions</p>}
    </div>
  );
}

function DraftReport({ data }: { data: any }) {
  const drafts: DraftClause[] = data.drafts || [];
  return (
    <div className="p-4 space-y-3">
      {drafts.map((clause, i) => (
        <div key={i} className="rounded-lg p-3" style={{ border: "1px solid var(--border)" }}>
          <p className="text-sm whitespace-pre-wrap mb-2" style={{ color: "var(--text)" }}>{clause.text}</p>
          <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            <span className="text-indigo-400">{clause.article_ref}</span> — {clause.rationale}
          </div>
        </div>
      ))}
      {drafts.length === 0 && <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>No draft clauses</p>}
    </div>
  );
}
