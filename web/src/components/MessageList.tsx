import { useEffect, useRef } from "react";
import { FileText, ExternalLink } from "lucide-react";
import type { ChatMessage, Artifact } from "../api/types";

interface Props {
  messages: ChatMessage[];
  loading: boolean;
  onArtifactClick: (artifact: Artifact) => void;
}

export default function MessageList({ messages, loading, onArtifactClick }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <div className="px-4 py-6 space-y-6" style={{ maxWidth: "48rem", margin: "0 auto" }}>
      {messages.map((msg) => (
        <div key={msg.id} className="animate-fade-in">
          {msg.role === "user" ? (
            <div className="flex justify-end">
              <div className="max-w-[80%]">
                {msg.files && msg.files.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2 justify-end">
                    {msg.files.map((f, i) => (
                      <div key={i} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs"
                        style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
                        <FileText size={12} />
                        <span className="truncate max-w-[120px]">{f.name}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="rounded-2xl rounded-br-md px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap"
                  style={{ background: "var(--user-bubble)", color: "var(--text)" }}>
                  {msg.content}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex justify-start">
              <div className="max-w-[85%] space-y-3">
                <div className="text-[15px] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text)" }}>
                  {msg.content}
                </div>
                {msg.artifact && (
                  <button
                    onClick={() => onArtifactClick(msg.artifact!)}
                    className="flex items-center gap-3 w-full rounded-xl px-4 py-3 text-left transition-colors group"
                    style={{ background: "var(--bg-input)", border: "1px solid var(--border)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "var(--bg-input)")}
                  >
                    <div className="w-10 h-10 rounded-lg bg-indigo-500/15 flex items-center justify-center shrink-0">
                      <FileText size={18} className="text-indigo-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>{msg.artifact.title}</p>
                      <p className="text-xs capitalize" style={{ color: "var(--text-muted)" }}>{msg.artifact.type} report</p>
                    </div>
                    <ExternalLink size={16} className="shrink-0 transition-colors" style={{ color: "var(--text-muted)" }} />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      ))}

      {loading && (
        <div className="flex justify-start animate-fade-in">
          <div className="flex gap-1.5 px-4 py-3">
            <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "var(--text-muted)" }} />
            <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "var(--text-muted)" }} />
            <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "var(--text-muted)" }} />
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
