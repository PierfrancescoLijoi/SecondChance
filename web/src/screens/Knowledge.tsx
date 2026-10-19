import { useState } from "react";
import { post, type Answer, type Hit } from "../api";
import { useI18n } from "../i18n";

export function Knowledge() {
  const { t, errorText } = useI18n();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: "search" | "answer") {
    setError(null);
    try {
      if (kind === "search") {
        setAnswer(null);
        setHits(await post<Hit[]>("/knowledge/search", { query }));
      } else {
        setHits(null);
        setAnswer(await post<Answer>("/knowledge/answer", { question: query }));
      }
    } catch (e) {
      setError(errorText(e, "knowledge.failed"));
    }
  }

  return (
    <section aria-labelledby="knowledge-title" className="stack">
      <h1 id="knowledge-title">{t("knowledge.title")}</h1>
      <p className="muted">{t("knowledge.intro")}</p>
      <form className="card stack" onSubmit={(e) => { e.preventDefault(); void run("answer"); }}>
        <label htmlFor="knowledge-query">{t("knowledge.query")}</label>
        <input id="knowledge-query" value={query} onChange={(e) => setQuery(e.target.value)} minLength={3} maxLength={500} required />
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button type="submit">{t("knowledge.ask")}</button>
          <button type="button" className="secondary" onClick={() => void run("search")} disabled={query.length < 2}>{t("knowledge.search")}</button>
        </div>
      </form>
      <div aria-live="polite">
        {error && <p className="notice error">{error}</p>}
        {answer && <AnswerView answer={answer} />}
        {hits && (hits.length === 0
          ? <p className="notice info">{t("knowledge.noHits")}</p>
          : hits.map((h) => <SourceView key={h.chunk_id} hit={h} />))}
      </div>
    </section>
  );
}

export function AnswerView({ answer }: { answer: Answer }) {
  const { t } = useI18n();
  if (answer.abstained) return <p className="notice warn">{t("answer.abstained")}</p>;
  return (
    <article className="card stack" aria-label={t("answer.label")}>
      <span className="ai-label">{t(answer.mode === "generated" ? "ai.withSources" : "ai.extracted")}</span>
      <p style={{ whiteSpace: "pre-line" }}>{answer.answer}</p>
      <h2>{t("answer.sources")}</h2>
      {answer.cited.map((n) => answer.sources[n - 1] && <SourceView key={n} index={n} hit={answer.sources[n - 1]} />)}
    </article>
  );
}

function SourceView({ hit, index }: { hit: Hit; index?: number }) {
  const { t } = useI18n();
  const pages = hit.page_start === hit.page_end
    ? `${t("source.page")} ${hit.page_start}`
    : `${t("source.pages")} ${hit.page_start}-${hit.page_end}`;
  return (
    <div className="source" lang={hit.language}>
      <div className="meta">
        {index !== undefined && <strong>[{index}] </strong>}
        {hit.title} · {t("source.version")} {hit.version ?? "-"} · {hit.section_path.join(" › ") || t("source.document")} · {pages}
      </div>
      <p>{hit.snippet}</p>
    </div>
  );
}
