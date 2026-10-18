import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "./api";
import { da } from "./locales/da";
import { en, type MessageKey, type Messages } from "./locales/en";
import { it } from "./locales/it";
import { pl } from "./locales/pl";

// English by default; the choice is remembered per browser. Missing keys fail the type check.
export const LANGUAGES = { en: "English", da: "Dansk", pl: "Polski", it: "Italiano" } as const;
export type Lang = keyof typeof LANGUAGES;

const MESSAGES: Record<Lang, Messages> = { en, da, pl, it };
const LOCALES: Record<Lang, string> = { en: "en-GB", da: "da-DK", pl: "pl-PL", it: "it-IT" };
const STORAGE_KEY = "secondchance.lang";

function storedLang(): Lang {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value && value in LANGUAGES) return value as Lang;
  } catch {
    // storage blocked: fall back to English
  }
  return "en";
}

type I18n = {
  lang: Lang;
  locale: string;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string>) => string;
  /** Dynamic lookup for values coming from the API ("status", "available"); unknown values pass through. */
  label: (group: string, value: string) => string;
  /** User-facing text for a failed request. */
  errorText: (error: unknown, fallback: MessageKey) => string;
};

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(storedLang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not remembered, still applied
    }
  }, []);

  const value = useMemo<I18n>(() => {
    const messages: Record<string, string> = MESSAGES[lang];
    const t = (key: MessageKey, vars: Record<string, string> = {}) =>
      messages[key].replace(/\{(\w+)\}/g, (_, name: string) => vars[name] ?? "");
    return {
      lang,
      locale: LOCALES[lang],
      setLang,
      t,
      label: (group, raw) => messages[`${group}.${raw}`] ?? raw,
      errorText: (error, fallback) => {
        if (!(error instanceof ApiError)) return t(fallback);
        return error.status === 429 ? t("error.rateLimited") : error.message;
      },
    };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n outside I18nProvider");
  return context;
}

export function LanguagePicker() {
  const { lang, setLang, t } = useI18n();
  return (
    <label>
      <span className="visually-hidden">{t("app.language")}</span>
      <select value={lang} onChange={(event) => setLang(event.target.value as Lang)}>
        {Object.entries(LANGUAGES).map(([code, name]) => (
          <option key={code} value={code} lang={code}>{name}</option>
        ))}
      </select>
    </label>
  );
}
