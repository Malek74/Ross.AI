import { useState, useRef, useCallback } from "react";
import { Paperclip, ArrowUp, X, FileText } from "lucide-react";
import type { AgentInfo, FileAttachment } from "../api/types";
import { useApp } from "../context";
import AgentPicker from "./AgentPicker";

interface Props {
  onSend: (text: string, files: FileAttachment[]) => void;
  loading: boolean;
  files: FileAttachment[];
  onFilesChange: (files: FileAttachment[]) => void;
  agents: AgentInfo[];
  routeMode: "auto" | "manual";
  selectedAgents: string[];
  onRouteChange: (mode: "auto" | "manual") => void;
  onAgentsChange: (agents: string[]) => void;
}

export default function ChatInput({
  onSend, loading, files, onFilesChange,
  agents, routeMode, selectedAgents, onRouteChange, onAgentsChange,
}: Props) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { s } = useApp();

  const handleSubmit = () => {
    const trimmed = text.trim();
    if ((!trimmed && files.length === 0) || loading) return;
    onSend(trimmed || s.auditDefault, files);
    setText("");
    onFilesChange([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList) return;
      const newFiles: FileAttachment[] = Array.from(fileList).map((f) => ({
        name: f.name, size: f.size, type: f.type, file: f,
      }));
      onFilesChange([...files, ...newFiles]);
    },
    [files, onFilesChange],
  );

  const removeFile = (index: number) => onFilesChange(files.filter((_, i) => i !== index));

  const handleDrop = useCallback(
    (e: React.DragEvent) => { e.preventDefault(); handleFiles(e.dataTransfer.files); },
    [handleFiles],
  );

  const canSend = text.trim() || files.length > 0;

  return (
    <div
      className="rounded-2xl transition-colors"
      style={{ background: "var(--bg-input)", border: "1px solid var(--border)" }}
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      {/* File chips */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 px-4 pt-3">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm"
              style={{ background: "var(--bg-hover)", color: "var(--text)" }}>
              <FileText size={14} style={{ color: "var(--text-muted)" }} className="shrink-0" />
              <span className="truncate max-w-[150px]">{f.name}</span>
              <button onClick={() => removeFile(i)} className="transition-colors"
                style={{ color: "var(--text-muted)" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}>
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Text input */}
      <div className="flex items-end gap-2 px-4 pt-3 pb-1">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={s.placeholder}
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-base leading-6 max-h-[200px]"
          style={{ color: "var(--text)" }}
          disabled={loading}
        />
      </div>

      {/* Bottom toolbar */}
      <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
        <div className="flex items-center gap-1">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: "var(--text-muted)" }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "var(--text)"; e.currentTarget.style.background = "var(--bg-hover)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-muted)"; e.currentTarget.style.background = "transparent"; }}
            title={s.attachFiles}
          >
            <Paperclip size={20} />
          </button>
          <input ref={fileInputRef} type="file" multiple accept=".pdf,.docx,.txt" className="hidden"
            onChange={(e) => handleFiles(e.target.files)} />
          <AgentPicker agents={agents} routeMode={routeMode} selectedAgents={selectedAgents}
            onRouteChange={onRouteChange} onAgentsChange={onAgentsChange} />
        </div>

        <button
          onClick={handleSubmit}
          disabled={loading || !canSend}
          className="p-2 rounded-full transition-all"
          style={{
            background: canSend && !loading ? "var(--send-bg)" : "var(--send-disabled-bg)",
            color: canSend && !loading ? "var(--send-text)" : "var(--send-disabled-text)",
            cursor: canSend && !loading ? "pointer" : "not-allowed",
          }}
        >
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  );
}
