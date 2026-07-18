import { FileSearch, RefreshCw, PenTool, MessageSquare, Upload, Scale } from "lucide-react";
import { useApp } from "../context";

interface Props {
  hasFiles: boolean;
  hasContract: boolean;
  hasAudit: boolean;
  onSelect: (text: string) => void;
}

export default function Suggestions({ hasFiles, hasContract, hasAudit, onSelect }: Props) {
  const { s } = useApp();

  type Sug = { icon: typeof FileSearch; label: string; text: string };
  let suggestions: Sug[];

  if (hasFiles) {
    suggestions = [
      { icon: FileSearch, label: s.suggestAuditRisks, text: s.suggestAuditRisksText },
      { icon: Scale, label: s.suggestCheckClauses, text: s.suggestCheckClausesText },
      { icon: MessageSquare, label: s.suggestSummarize, text: s.suggestSummarizeText },
    ];
  } else if (hasAudit) {
    suggestions = [
      { icon: RefreshCw, label: s.suggestRevise, text: s.suggestReviseText },
      { icon: MessageSquare, label: s.suggestExplain, text: s.suggestExplainText },
      { icon: PenTool, label: s.suggestDraftReplacement, text: s.suggestDraftReplacementText },
    ];
  } else if (hasContract) {
    suggestions = [
      { icon: FileSearch, label: s.suggestAuditContract, text: s.suggestAuditContractText },
      { icon: MessageSquare, label: s.suggestAskClause, text: s.suggestAskClauseText },
      { icon: RefreshCw, label: s.suggestReviseCompliance, text: s.suggestReviseComplianceText },
    ];
  } else {
    suggestions = [
      { icon: Upload, label: s.suggestUpload, text: s.suggestUploadText },
      { icon: PenTool, label: s.suggestDraft, text: s.suggestDraftText },
      { icon: MessageSquare, label: s.suggestAsk, text: s.suggestAskText },
    ];
  }

  return (
    <div className="flex flex-wrap gap-2 mt-4 justify-center">
      {suggestions.map((sg, i) => {
        const Icon = sg.icon;
        return (
          <button
            key={i}
            onClick={() => onSelect(sg.text)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-full text-sm transition-colors"
            style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-input)"; e.currentTarget.style.color = "var(--text)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-secondary)"; }}
          >
            <Icon size={14} />
            {sg.label}
          </button>
        );
      })}
    </div>
  );
}
