import { useCallback, useEffect, useState } from "react";
import { api, ApiError, post, type DocumentRow, type Job, type Space } from "../api";
import { useI18n } from "../i18n";

const MAX_BYTES = 20 * 1024 * 1024;
const DOCUMENT_LANGUAGES = ["en", "da", "pl", "it"];
const DOCUMENT_TYPES = ["procedure", "guideline", "regulation", "manual", "other"];

export function Documents({ tenantId }: { tenantId: string }) {
  const { t, label, locale, errorText } = useI18n();
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const languageName = new Intl.DisplayNames([locale], { type: "language" });

  const load = useCallback(() => {
    api<Space[]>("/knowledge/spaces").then((all) => setSpaces(all.filter((s) => s.tenant_id === tenantId))).catch(() => undefined);
    api<DocumentRow[]>("/documents").then(setDocuments).catch(() => undefined);
  }, [tenantId]);
  useEffect(load, [load]);

  useEffect(() => {
    if (!job || !["uploaded", "processing"].includes(job.status)) return;
    const id = setTimeout(() => {
      api<Job>(`/ingestion/jobs/${job.id}`).then((next) => { setJob(next); if (next.status === "published") load(); }).catch(() => undefined);
    }, 1500);
    return () => clearTimeout(id);
  }, [job, load]);

  async function handleUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const file = form.get("file") as File | null;
    // Same checks as the server, before sending 20 MB over the network (ADR-016).
    if (!file || file.type !== "application/pdf") return setError(t("documents.notPdf"));
    if (file.size > MAX_BYTES) return setError(t("documents.tooBig"));
    try {
      setJob(await post<Job>("/documents", form));
      event.currentTarget.reset();
    } catch (e) {
      setError(e instanceof ApiError && e.status !== 429 ? `${t("documents.rejected")} ${e.message}` : errorText(e, "documents.failed"));
    }
  }

  const jobTone = job?.status === "failed" ? "error" : job?.status === "published" ? "ok" : "info";

  return (
    <section aria-labelledby="documents-title" className="stack">
      <h1 id="documents-title">{t("documents.title")}</h1>
      <form className="card stack" onSubmit={(e) => void handleUpload(e)}>
        <h2>{t("documents.uploadTitle")}</h2>
        <p className="muted">{t("documents.uploadHint")}</p>
        <div aria-live="polite">
          {error && <p className="notice error">{error}</p>}
          {job && (
            <p className={`notice ${jobTone}`}>
              {t("documents.processing")} {label("jobStatus", job.status)}{job.error_category ? ` (${job.error_category})` : ""}
            </p>
          )}
        </div>
        <div className="grid-2">
          <div><label htmlFor="title">{t("documents.titleField")}</label><input id="title" name="title" minLength={2} maxLength={200} required /></div>
          <div>
            <label htmlFor="space">{t("documents.space")}</label>
            <select id="space" name="space_id" required>{spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          </div>
          <div>
            <label htmlFor="language">{t("documents.language")}</label>
            <select id="language" name="language">
              {DOCUMENT_LANGUAGES.map((code) => <option key={code} value={code}>{languageName.of(code)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="document_type">{t("documents.type")}</label>
            <select id="document_type" name="document_type">
              {DOCUMENT_TYPES.map((value) => <option key={value} value={value}>{label("docType", value)}</option>)}
            </select>
          </div>
        </div>
        <div><label htmlFor="file">{t("documents.file")}</label><input id="file" name="file" type="file" accept="application/pdf" required /></div>
        <button type="submit" disabled={spaces.length === 0}>{t("documents.upload")}</button>
      </form>
      <div className="table-wrap">
        <table>
          <caption className="visually-hidden">{t("documents.title")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("documents.titleField")}</th><th scope="col">{t("documents.language")}</th>
              <th scope="col">{t("documents.activeVersion")}</th><th scope="col">{t("documents.action")}</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => (
              <tr key={d.id}>
                <td lang={d.language}>{d.title}</td><td>{languageName.of(d.language)}</td><td>{d.active_version ?? t("documents.inProgress")}</td>
                <td><button className="danger" onClick={() => void post(`/documents/${d.id}/delete`).then(load)}>{t("documents.delete")}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
