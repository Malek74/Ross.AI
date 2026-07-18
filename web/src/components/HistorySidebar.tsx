import { MessageSquare, Plus, Trash2, X, Eraser } from "lucide-react";
import type { Conversation } from "../api/types";
import { useApp } from "../context";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  open: boolean;
  onToggle: () => void;
  onSelect: (convo: Conversation) => void;
  onDelete: (id: string) => void;
  onNewChat: () => void;
  onClearAll: () => void;
}

export default function HistorySidebar({ conversations, activeId, open, onToggle, onSelect, onDelete, onNewChat, onClearAll }: Props) {
  const { s } = useApp();

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onToggle} />
      )}
      <div
        className={`fixed lg:relative z-40 h-full flex flex-col transition-all duration-300 ${
          open ? "w-64" : "w-0"
        } overflow-hidden shrink-0`}
        style={{ background: "var(--bg-secondary)", borderRight: open ? "1px solid var(--border)" : "none" }}
      >
        <div className="flex items-center justify-between px-3 py-3 shrink-0">
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>{s.history}</span>
          <div className="flex items-center gap-1">
            <button onClick={onNewChat} className="p-1.5 rounded-lg transition-colors"
              style={{ color: "var(--text-muted)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; e.currentTarget.style.color = "var(--text)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; }}
              title={s.newChat}>
              <Plus size={16} />
            </button>
            {conversations.length > 0 && (
              <button onClick={onClearAll} className="p-1.5 rounded-lg transition-colors"
                style={{ color: "var(--text-muted)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; e.currentTarget.style.color = "var(--severity-high-text)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-muted)"; }}>
                <Eraser size={14} />
              </button>
            )}
            <button onClick={onToggle} className="p-1.5 rounded-lg transition-colors lg:hidden"
              style={{ color: "var(--text-muted)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
          {conversations.map((convo) => (
            <div key={convo.id}
              className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer transition-colors ${
                activeId === convo.id ? "ring-1 ring-indigo-500/50" : ""
              }`}
              style={{ background: activeId === convo.id ? "var(--bg-hover)" : "transparent" }}
              onClick={() => onSelect(convo)}
              onMouseEnter={(e) => { if (activeId !== convo.id) e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={(e) => { if (activeId !== convo.id) e.currentTarget.style.background = "transparent"; }}
            >
              <MessageSquare size={14} className="shrink-0" style={{ color: "var(--text-muted)" }} />
              <span className="flex-1 text-sm truncate" style={{ color: "var(--text-secondary)" }}>
                {convo.title}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(convo.id); }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded transition-all"
                style={{ color: "var(--text-muted)" }}
                onMouseEnter={(e) => { e.currentTarget.style.color = "var(--severity-high-text)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-muted)"; }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
          {conversations.length === 0 && (
            <p className="text-xs text-center py-6" style={{ color: "var(--text-muted)" }}>{s.noHistory}</p>
          )}
        </div>
      </div>
    </>
  );
}
