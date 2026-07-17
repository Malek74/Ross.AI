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
      { icon: FileSearch, label: s.suggestAuditRisks, text: "Audit this contract for compliance risks under Egyptian law" },
      { icon: Scale, label: s.suggestCheckClauses, text: "Review the termination and penalty clauses for legal compliance" },
      { icon: MessageSquare, label: s.suggestSummarize, text: "Summarize the key obligations and rights in this contract" },
    ];
  } else if (hasAudit) {
    suggestions = [
      { icon: RefreshCw, label: s.suggestRevise, text: "Revise all flagged clauses to comply with the cited articles" },
      { icon: MessageSquare, label: s.suggestExplain, text: "Explain why the penalty clause was flagged and what the law requires" },
      { icon: PenTool, label: s.suggestDraftReplacement, text: "Draft a compliant version of the flagged clauses" },
    ];
  } else if (hasContract) {
    suggestions = [
      { icon: FileSearch, label: s.suggestAuditContract, text: "Audit this contract for compliance risks under Egyptian law" },
      { icon: MessageSquare, label: s.suggestAskClause, text: "Is the termination clause in this contract enforceable?" },
      { icon: RefreshCw, label: s.suggestReviseCompliance, text: "Revise any non-compliant clauses to meet Egyptian Civil Code requirements" },
    ];
  } else {
    suggestions = [
      { icon: Upload, label: s.suggestUpload, text: "Upload a contract to audit for legal risks" },
      { icon: PenTool, label: s.suggestDraft, text: "Draft an employment contract compliant with Egyptian labour law" },
      { icon: MessageSquare, label: s.suggestAsk, text: "What are the requirements for a valid contract under Egyptian Civil Code?" },
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
