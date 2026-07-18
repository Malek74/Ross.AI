import { useState } from "react";
import { ChevronDown, ChevronRight, Brain, Search, Users, Merge, CheckCircle, Loader } from "lucide-react";
import type { StepEvent } from "../api/types";
import { useApp } from "../context";

interface Props {
  steps: StepEvent[];
  isActive: boolean;
}

const ICONS: Record<string, typeof Brain> = {
  thinking: Brain,
  classify: Search,
  consult: Users,
  synthesize: Merge,
  finish: CheckCircle,
};

export default function ThinkingSteps({ steps, isActive }: Props) {
  const [expanded, setExpanded] = useState(false);
  const { s } = useApp();

  const domainNames: Record<string, string> = { civil: s.domainCivil, commercial: s.domainCommercial, labour: s.domainLabour };
  const describe = (step: StepEvent): string => {
    switch (step.action) {
      case "thinking": return s.stepThinking;
      case "classify": return s.stepClassify;
      case "consult": return s.stepConsult.replace("{domain}", domainNames[step.domain || ""] || step.domain || "");
      case "synthesize": return s.stepSynthesize;
      case "finish": return s.stepFinish;
      default: return step.detail || s.stepWorking;
    }
  };

  if (steps.length === 0) return null;

  const latestStep = steps[steps.length - 1];

  return (
    <div className="mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors w-full"
        style={{ color: "var(--text-muted)" }}
        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
      >
        {isActive ? (
          <Loader size={13} className="animate-spin shrink-0" style={{ color: "var(--accent)" }} />
        ) : (
          <CheckCircle size={13} className="shrink-0" style={{ color: "var(--accent)" }} />
        )}
        <span className="flex-1 text-start truncate">
          {isActive ? describe(latestStep) : s.analyzedInSteps.replace("{n}", String(steps.length))}
        </span>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {expanded && (
        <div className="mt-1 ms-3 border-s-2 ps-3 space-y-1" style={{ borderColor: "var(--border)" }}>
          {steps.map((step, i) => {
            const Icon = ICONS[step.action] || Brain;
            const isDone = i < steps.length - 1 || !isActive;
            return (
              <div key={i} className="flex items-start gap-2 py-1 text-xs">
                <Icon size={12} className="mt-0.5 shrink-0"
                  style={{ color: isDone ? "var(--accent)" : "var(--text-muted)" }} />
                <div className="min-w-0">
                  <span style={{ color: isDone ? "var(--text-secondary)" : "var(--text-muted)" }}>
                    {describe(step)}
                  </span>
                  {step.reason && (
                    <p className="truncate" style={{ color: "var(--text-muted)" }}>
                      {step.reason}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
