import { useState, useMemo, useEffect, useRef } from "react";
import { X, AlertTriangle, AlertCircle, Info, ChevronDown, ChevronRight, FileText, Loader, Download } from "lucide-react";
import Markdown from "react-markdown";
import type { Artifact, Flag, Revision, DraftClause } from "../api/types";
import { highlightPdf } from "../api/client";
import { useApp } from "../context";
import type { Strings } from "../i18n";

interface Props {
  artifact: Artifact;
  onClose: () => void;
}

type PanelTab = "report" | "contract";

function PageShell({ children, dir }: { children: React.ReactNode; dir?: string }) {
  return (
    <div className="p-6 flex justify-center">
      <div
        dir={dir}
        className="pdf-page w-full rounded-sm shadow-lg"
        style={{
          background: "#fff",
          color: "#1a1a1a",
          padding: "48px 40px",
          minHeight: "600px",
          maxWidth: "540px",
          fontFamily: "'Noto Sans Arabic', 'Segoe UI', system-ui, sans-serif",
          lineHeight: 1.8,
          fontSize: "13px",
        }}
      >
        {children}
      </div>
    </div>
  );
}

export default function ArtifactPanel({ artifact, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<PanelTab>("report");
  const [activeFlag, setActiveFlag] = useState<Flag | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const { s } = useApp();
  const hasContract = !!artifact.contractText;

  useEffect(() => { setPdfUrl(null); }, [artifact]);

  const handleDownload = () => {
    if (activeTab === "contract" && pdfUrl) {
      const a = document.createElement("a");
      a.href = pdfUrl;
      a.download = (artifact.file?.name || "contract").replace(/\.pdf$/i, "") + "-highlighted.pdf";
      a.click();
      return;
    }
    if (activeTab === "contract" && artifact.contractText) {
      const isAr = /[؀-ۿ]/.test(artifact.contractText.slice(0, 200));
      openPrintWindow(artifact.title, `<div style="white-space:pre-wrap">${esc(artifact.contractText)}</div>`, isAr);
      return;
    }
    const html = buildReportHtml(artifact, s);
    const isAr = /[؀-ۿ]/.test((artifact.data?.summary || "") + JSON.stringify(artifact.data?.flags_by_domain || {}).slice(0, 300));
    openPrintWindow(artifact.title, html, isAr);
  };

  return (
    <div className="w-[520px] shrink-0 flex flex-col animate-fade-in"
      style={{ borderLeft: "1px solid var(--border)", background: "var(--bg)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2 min-w-0">
          <FileText size={16} className="text-indigo-400 shrink-0" />
          <span className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>{artifact.title}</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handleDownload} className="p-1 rounded-md transition-colors" title={s.download}
            style={{ color: "var(--text-muted)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-input)"; e.currentTarget.style.color = "var(--text)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; }}>
            <Download size={16} />
          </button>
          <button onClick={onClose} className="p-1 rounded-md transition-colors"
            style={{ color: "var(--text-muted)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-input)"; e.currentTarget.style.color = "var(--text)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; }}>
            <X size={18} />
          </button>
        </div>
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

      <div className="flex-1 overflow-y-auto scrollbar-thin" style={{ background: "var(--bg-secondary)" }}>
        {activeTab === "report" ? (
          <ReportContent artifact={artifact} activeFlag={activeFlag}
            onFlagClick={(f) => { setActiveFlag(f); if (hasContract) setActiveTab("contract"); }} />
        ) : artifact.file ? (
          <PdfContract file={artifact.file} onUrl={setPdfUrl}
            flags={Object.values((artifact.data?.flags_by_domain || {}) as Record<string, Flag[]>).flat()}
            fallback={<ContractContent text={artifact.contractText || ""} activeFlag={activeFlag}
              flags={Object.values((artifact.data?.flags_by_domain || {}) as Record<string, Flag[]>).flat()} />} />
        ) : (
          <ContractContent text={artifact.contractText || ""} activeFlag={activeFlag}
            flags={Object.values((artifact.data?.flags_by_domain || {}) as Record<string, Flag[]>).flat()} />
        )}
      </div>
    </div>
  );
}

function PdfContract({ file, flags, fallback, onUrl }: { file: File; flags: Flag[]; fallback: React.ReactNode; onUrl?: (url: string | null) => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    let objectUrl: string | null = null;
    highlightPdf(file, flags.filter((f) => f.evidence_span).map((f) => ({ evidence_span: f.evidence_span, severity: f.severity || "medium" })))
      .then((r) => {
        if (!alive) { URL.revokeObjectURL(r.url); return; }
        objectUrl = r.url;
        setUrl(r.url);
        onUrl?.(r.url);
      })
      .catch(() => { if (alive) setFailed(true); });
    return () => {
      alive = false;
      onUrl?.(null);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file, flags]);

  if (failed) return <>{fallback}</>;
  if (!url) {
    return (
      <div className="flex items-center justify-center h-full py-16">
        <Loader size={20} className="animate-spin" style={{ color: "var(--text-muted)" }} />
      </div>
    );
  }
  return <iframe src={url} title="contract" className="w-full" style={{ height: "100%", minHeight: 600, border: "none", background: "#fff" }} />;
}

const SEVERITY_MARK: Record<string, { bg: string; border: string }> = {
  high: { bg: "rgba(220, 38, 38, 0.22)", border: "#dc2626" },
  medium: { bg: "rgba(245, 158, 11, 0.28)", border: "#f59e0b" },
  low: { bg: "rgba(59, 130, 246, 0.22)", border: "#3b82f6" },
};

function ContractContent({ text, flags, activeFlag }: { text: string; flags: Flag[]; activeFlag: Flag | null }) {
  const activeRef = useRef<HTMLElement | null>(null);

  const segments = useMemo(() => {
    if (!text) return [];
    const matches: { start: number; end: number; flag: Flag }[] = [];
    for (const f of flags) {
      if (!f.evidence_span) continue;
      const span = f.evidence_span.trim();
      let idx = text.indexOf(span);
      let end = idx + span.length;
      if (idx === -1) {
        // model quotes often drift from the source — retry with the first words
        const words = span.split(/\s+/);
        if (words.length >= 4) {
          const needle = words.slice(0, 6).join(" ");
          idx = text.indexOf(needle);
          if (idx !== -1) end = idx + needle.length;
        }
        if (idx === -1) continue;
      }
      // expand to whole-word boundaries so highlights don't slice words
      while (idx > 0 && !/\s/.test(text[idx - 1])) idx--;
      while (end < text.length && !/[\s.،؛,;]/.test(text[end])) end++;
      matches.push({ start: idx, end, flag: f });
    }
    matches.sort((a, b) => a.start - b.start);
    // drop overlapping spans, keep the earliest
    const kept: typeof matches = [];
    let lastEnd = 0;
    for (const m of matches) {
      if (m.start >= lastEnd) { kept.push(m); lastEnd = m.end; }
    }
    // build alternating plain/highlight segments
    const segs: { text: string; flag?: Flag }[] = [];
    let pos = 0;
    for (const m of kept) {
      if (m.start > pos) segs.push({ text: text.slice(pos, m.start) });
      segs.push({ text: text.slice(m.start, m.end), flag: m.flag });
      pos = m.end;
    }
    if (pos < text.length) segs.push({ text: text.slice(pos) });
    return segs;
  }, [text, flags]);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeFlag]);

  const isArabic = /[؀-ۿ]/.test(text.slice(0, 200));

  return (
    <PageShell dir={isArabic ? "rtl" : "ltr"}>
      <div className="whitespace-pre-wrap" style={{ textAlign: isArabic ? "right" : "left" }}>
        {segments.length > 0
          ? segments.map((seg, i) => {
              if (!seg.flag) return <span key={i}>{seg.text}</span>;
              const sev = SEVERITY_MARK[(seg.flag.severity || "medium").toLowerCase()] || SEVERITY_MARK.medium;
              const isActive = seg.flag === activeFlag;
              return (
                <mark
                  key={i}
                  ref={isActive ? activeRef : undefined}
                  title={`${seg.flag.article_ref || ""} — ${seg.flag.label || ""}`}
                  style={{
                    background: sev.bg,
                    borderBottom: `2px solid ${sev.border}`,
                    borderRadius: 2,
                    padding: "0 2px",
                    outline: isActive ? `2px solid ${sev.border}` : "none",
                    color: "inherit",
                  }}
                >
                  {seg.text}
                </mark>
              );
            })
          : text}
      </div>
    </PageShell>
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
  const domainNames: Record<string, string> = { civil: s.domainCivil, commercial: s.domainCommercial, labour: s.domainLabour };
  const domainName = (d: string) => domainNames[d] || d;
  const hasFlags = Object.keys(flagsByDomain).length > 0;
  const isArabic = /[؀-ۿ]/.test((data.summary || "").slice(0, 100));

  if (!hasFlags && data.summary) {
    return (
      <PageShell dir={isArabic ? "rtl" : "ltr"}>
        {consulted.length > 0 && (
          <div style={{ fontSize: "11px", color: "#888", marginBottom: 16, textAlign: isArabic ? "right" : "left" }}>
            {s.consulted}: {consulted.map(domainName).join("، ")}
          </div>
        )}
        <div className="pdf-prose">
          <Markdown>{data.summary}</Markdown>
        </div>
      </PageShell>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {consulted.length > 0 && (
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{s.consulted}: {consulted.map(domainName).join(", ")}</div>
      )}
      {Object.entries(flagsByDomain).map(([domain, flags]) => (
        <div key={domain}>
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2 flex items-center gap-2"
            style={{ color: "var(--text-secondary)" }}>
            {domainName(domain)}
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
      {!hasFlags && !data.summary && (
        <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>{s.noFlags}</p>
      )}
    </div>
  );
}

function FlagCard({ flag, isActive, onClick }: { flag: Flag; isActive: boolean; onClick: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const { s } = useApp();
  const sev = ((flag.severity || "medium").toLowerCase() as "high" | "medium" | "low");
  const icons = { high: AlertTriangle, medium: AlertCircle, low: Info };
  const Icon = icons[sev] || AlertCircle;
  const sevLabels: Record<string, string> = { high: s.severityHigh, medium: s.severityMedium, low: s.severityLow };
  const sevLabel = sevLabels[sev] || String(flag.severity).toUpperCase();
  const title = flag.label || (flag.rationale || "").split(/[.،]/)[0].slice(0, 80) || flag.article_ref;

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
              {sevLabel}
            </span>
            <span className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>{flag.article_ref}</span>
          </div>
          <p className="text-sm font-medium mb-0.5" style={{ color: "var(--text)" }}>{title}</p>
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
  const isArabic = revisions.some(r => /[؀-ۿ]/.test(r.clause_original));
  return (
    <PageShell dir={isArabic ? "rtl" : "ltr"}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {revisions.map((rev, i) => (
          <div key={i} style={{ border: "1px solid #ddd", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr" }}>
              <div style={{ padding: 12, borderRight: "1px solid #ddd" }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", marginBottom: 4, color: "#dc2626" }}>{s.original}</div>
                <p style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{rev.clause_original}</p>
              </div>
              <div style={{ padding: 12 }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", marginBottom: 4, color: "#16a34a" }}>{s.revised}</div>
                <p style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{rev.clause_revised}</p>
              </div>
            </div>
            <div style={{ padding: "8px 12px", fontSize: 11, background: "#f5f5f5", borderTop: "1px solid #ddd", color: "#666" }}>
              <span style={{ color: "#6366f1" }}>{rev.article_ref}</span> — {rev.rationale}
            </div>
          </div>
        ))}
        {revisions.length === 0 && <p style={{ textAlign: "center", color: "#999", padding: "32px 0" }}>No revisions</p>}
      </div>
    </PageShell>
  );
}

function esc(str: string): string {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function openPrintWindow(title: string, bodyHtml: string, rtl: boolean) {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(`<!doctype html><html dir="${rtl ? "rtl" : "ltr"}" lang="${rtl ? "ar" : "en"}"><head><meta charset="utf-8"><title>${esc(title)}</title><style>
    body { font-family: 'Noto Sans Arabic', 'Segoe UI', system-ui, sans-serif; color: #1a1a1a; line-height: 1.8; font-size: 13px; padding: 40px; max-width: 720px; margin: 0 auto; }
    h1 { font-size: 20px; margin: 0 0 4px; } h2 { font-size: 15px; margin: 20px 0 8px; }
    .meta { font-size: 11px; color: #888; margin-bottom: 20px; }
    .flag { border: 1px solid #ddd; border-radius: 6px; padding: 12px; margin-bottom: 10px; page-break-inside: avoid; }
    .badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; color: #fff; }
    .high { background: #dc2626; } .medium { background: #f59e0b; } .low { background: #3b82f6; }
    .ref { font-size: 11px; color: #6366f1; margin-inline-start: 8px; }
    .label { font-weight: 600; margin: 6px 0 2px; }
    blockquote { border-inline-start: 3px solid #ddd; margin: 8px 0; padding: 4px 12px; font-style: italic; color: #555; background: #fafafa; }
    .rationale { font-size: 12px; color: #444; }
    .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; margin-bottom: 10px; page-break-inside: avoid; }
    .pair > div { padding: 10px; font-size: 12px; white-space: pre-wrap; }
    .pair .orig { border-inline-end: 1px solid #ddd; }
    .tag { font-size: 9px; font-weight: 700; text-transform: uppercase; display: block; margin-bottom: 4px; }
    .summary { white-space: pre-wrap; margin-bottom: 16px; }
    @media print { body { padding: 0; } }
  </style></head><body>${bodyHtml}</body></html>`);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 400);
}

function buildReportHtml(artifact: Artifact, s: Strings): string {
  const parts: string[] = [`<h1>${esc(artifact.title)}</h1>`];
  const data = artifact.data || {};
  const domainNames: Record<string, string> = { civil: s.domainCivil, commercial: s.domainCommercial, labour: s.domainLabour };
  const sevLabels: Record<string, string> = { high: s.severityHigh, medium: s.severityMedium, low: s.severityLow };

  if (artifact.type === "audit") {
    const consulted: string[] = data.routing?.consulted || [];
    if (consulted.length) parts.push(`<div class="meta">${esc(s.consulted)}: ${esc(consulted.map((d) => domainNames[d] || d).join("، "))}</div>`);
    if (data.summary) parts.push(`<div class="summary">${esc(data.summary)}</div>`);
    for (const [domain, flags] of Object.entries((data.flags_by_domain || {}) as Record<string, Flag[]>)) {
      parts.push(`<h2>${esc(domainNames[domain] || domain)}</h2>`);
      for (const f of flags) {
        const sev = (f.severity || "medium").toLowerCase();
        parts.push(`<div class="flag">
          <span class="badge ${sev}">${esc(sevLabels[sev] || sev)}</span><span class="ref">${esc(f.article_ref || "")}</span>
          <div class="label">${esc(f.label || "")}</div>
          ${f.evidence_span ? `<blockquote>${esc(f.evidence_span)}</blockquote>` : ""}
          <div class="rationale">${esc(f.rationale || "")}</div>
          ${f.article_ar ? `<div class="rationale" dir="rtl" style="margin-top:6px">${esc(f.article_ar)}</div>` : ""}
        </div>`);
      }
    }
  } else if (artifact.type === "revision") {
    if (data.summary) parts.push(`<div class="summary">${esc(data.summary)}</div>`);
    for (const rev of (data.revisions || []) as Revision[]) {
      parts.push(`<div class="pair">
        <div class="orig"><span class="tag" style="color:#dc2626">${esc(s.original)}</span>${esc(rev.clause_original)}</div>
        <div><span class="tag" style="color:#16a34a">${esc(s.revised)}</span>${esc(rev.clause_revised)}</div>
      </div>
      <div class="meta"><span style="color:#6366f1">${esc(rev.article_ref || "")}</span> — ${esc(rev.rationale || "")}</div>`);
    }
  } else if (artifact.type === "draft") {
    if (data.summary) parts.push(`<div class="summary">${esc(data.summary)}</div>`);
    for (const clause of (data.drafts || []) as DraftClause[]) {
      parts.push(`<div class="flag">
        <div style="white-space:pre-wrap">${esc(clause.text)}</div>
        <div class="meta" style="margin:6px 0 0"><span style="color:#6366f1">${esc(clause.article_ref || "")}</span> — ${esc(clause.rationale || "")}</div>
      </div>`);
    }
  } else if (data.summary) {
    parts.push(`<div class="summary">${esc(data.summary)}</div>`);
  }
  return parts.join("\n");
}

function DraftReport({ data }: { data: any }) {
  const drafts: DraftClause[] = data.drafts || [];
  const isArabic = drafts.some(d => /[؀-ۿ]/.test(d.text));
  return (
    <PageShell dir={isArabic ? "rtl" : "ltr"}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {drafts.map((clause, i) => (
          <div key={i} style={{ border: "1px solid #ddd", borderRadius: 4, padding: 12 }}>
            <p style={{ fontSize: 13, whiteSpace: "pre-wrap", marginBottom: 8 }}>{clause.text}</p>
            <div style={{ fontSize: 11, color: "#666" }}>
              <span style={{ color: "#6366f1" }}>{clause.article_ref}</span> — {clause.rationale}
            </div>
          </div>
        ))}
        {drafts.length === 0 && <p style={{ textAlign: "center", color: "#999", padding: "32px 0" }}>No draft clauses</p>}
      </div>
    </PageShell>
  );
}
