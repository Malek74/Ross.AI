import { createContext, useContext } from "react";
import type { Lang, Strings } from "./i18n";
import { t } from "./i18n";

export type Theme = "dark" | "light";

interface AppContext {
  lang: Lang;
  theme: Theme;
  s: Strings;
}

export const AppCtx = createContext<AppContext>({ lang: "en", theme: "dark", s: t("en") });

export function useApp() {
  return useContext(AppCtx);
}
