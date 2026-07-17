import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check, Zap } from "lucide-react";
import type { AgentInfo } from "../api/types";
import { useApp } from "../context";

interface Props {
  agents: AgentInfo[];
  routeMode: "auto" | "manual";
  selectedAgents: string[];
  onRouteChange: (mode: "auto" | "manual") => void;
  onAgentsChange: (agents: string[]) => void;
}

export default function AgentPicker({ agents, routeMode, selectedAgents, onRouteChange, onAgentsChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { s } = useApp();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const currentLabel =
    routeMode === "auto"
      ? "Auto"
      : selectedAgents.length
        ? selectedAgents.map((d) => agents.find((a) => a.domain === d)?.label || d).join(", ")
        : "Ross.AI";

  const selectAgent = (domain: string) => {
    if (routeMode === "auto") {
      onRouteChange("manual");
      onAgentsChange([domain]);
    } else {
      if (selectedAgents.includes(domain)) {
        const next = selectedAgents.filter((d) => d !== domain);
        if (next.length === 0) { onRouteChange("auto"); onAgentsChange([]); }
        else onAgentsChange(next);
      } else {
        onAgentsChange([...selectedAgents, domain]);
      }
    }
  };

  const selectAuto = () => { onRouteChange("auto"); onAgentsChange([]); setOpen(false); };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-lg transition-colors text-sm font-medium"
        style={{ color: "var(--text-secondary)", background: open ? "var(--bg-hover)" : "transparent" }}
        onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
        onMouseLeave={(e) => (e.currentTarget.style.background = open ? "var(--bg-hover)" : "transparent")}
      >
        <span>{currentLabel}</span>
        <ChevronDown size={14} style={{ color: "var(--text-muted)" }} />
      </button>

      {open && (
        <div
          className="absolute bottom-full left-0 mb-2 w-72 rounded-xl shadow-2xl z-50 overflow-hidden animate-fade-in"
          style={{ background: "var(--bg-input)", border: "1px solid var(--border)" }}
        >
          <button
            onClick={selectAuto}
            className="w-full flex items-start gap-3 px-4 py-3 transition-colors text-left"
            style={{ color: "var(--text)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <Zap size={18} className="text-indigo-400 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{s.auto}</span>
                {routeMode === "auto" && <Check size={14} className="text-indigo-400" />}
              </div>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{s.autoDesc}</p>
            </div>
          </button>

          <div style={{ borderTop: "1px solid var(--border)" }} />

          {agents.map((agent) => (
            <button
              key={agent.domain}
              onClick={() => selectAgent(agent.domain)}
              disabled={!agent.live}
              className="w-full flex items-start gap-3 px-4 py-3 transition-colors text-left disabled:opacity-40 disabled:cursor-not-allowed"
              onMouseEnter={(e) => { if (agent.live) e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <div className={`w-5 h-5 rounded-md flex items-center justify-center text-xs font-bold mt-0.5 shrink-0 ${
                agent.live ? "bg-indigo-500/20 text-indigo-400" : "text-[var(--text-muted)]"
              }`} style={!agent.live ? { background: "var(--bg-hover)" } : undefined}>
                {agent.label.charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium" style={{ color: "var(--text)" }}>{agent.label}</span>
                  {!agent.live && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--bg-hover)", color: "var(--text-muted)" }}>
                      {s.soon}
                    </span>
                  )}
                  {routeMode === "manual" && selectedAgents.includes(agent.domain) && (
                    <Check size={14} className="text-indigo-400" />
                  )}
                </div>
                <p className="text-xs mt-0.5 line-clamp-1" style={{ color: "var(--text-muted)" }}>{agent.description}</p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
