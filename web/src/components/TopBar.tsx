import { Sun, Moon, Globe, Scale } from "lucide-react";
import type { Lang } from "../i18n";
import type { Theme } from "../context";

interface Props {
  lang: Lang;
  theme: Theme;
  onLangChange: (lang: Lang) => void;
  onThemeChange: (theme: Theme) => void;
}

export default function TopBar({ lang, theme, onLangChange, onThemeChange }: Props) {
  return (
    <header className="flex items-center justify-between px-4 py-2.5 shrink-0">
      <div className="flex items-center gap-2">
        <Scale size={20} className="text-indigo-400" />
        <span className="text-base font-semibold" style={{ color: "var(--text)" }}>Ross.AI</span>
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => onLangChange(lang === "en" ? "ar" : "en")}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm transition-colors"
          style={{ color: "var(--text-secondary)" }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          <Globe size={16} />
          <span className="font-medium">{lang === "en" ? "العربية" : "English"}</span>
        </button>

        <button
          onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
          className="p-2 rounded-lg transition-colors"
          style={{ color: "var(--text-secondary)" }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>
    </header>
  );
}
