import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, post, selectedTenant, type AgentRun, type AssistResult } from "../api";
import { currentToken } from "../auth";
import { config } from "../config";
import { useI18n } from "../i18n";
import type { MessageKey } from "../locales/en";
import { SCREENS } from "../nav";
import { openNegotiatedRunSocket, openRunSocket } from "../realtime";
import { AnswerView } from "./Knowledge";

// The API also returns an English message; the screen shows its own translation by kind.
const KIND_MESSAGES: Partial<Record<AssistResult["kind"], MessageKey>> = {
  clarify: "assist.clarify",
  unsupported: "assist.unsupported",
  unavailable: "assist.unavailable",
  not_allowed: "assist.notAllowed",
};

export function Assistant({ canRunAgents }: { canRunAgents: boolean }) {
  const { t, errorText } = useI18n();
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<AssistResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setIsBusy(true);
    setError(null);
    try {
      setResult(await post<AssistResult>("/assist", { message }));
    } catch (e) {
      setError(errorText(e, "assistant.failed"));
    } finally {
      setIsBusy(false);
    }
  }

  const examples = [
    t("assistant.example1"),
    ...(canRunAgents ? [t("assistant.example2")] : []),
    t("assistant.example3"),
  ];

  return (
    <section aria-labelledby="assistant-title" className="stack">
      <h1 id="assistant-title">{t("assistant.title")}</h1>
      <p className="muted">{t("assistant.intro")}</p>
      <form className="card stack" onSubmit={(e) => void handleSubmit(e)}>
        <label htmlFor="assist-message">{t("assistant.label")}</label>
        <textarea id="assist-message" value={message} onChange={(e) => setMessage(e.target.value)} minLength={2} maxLength={2000} required />
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button type="submit" disabled={isBusy}>{t(isBusy ? "assistant.busy" : "assistant.send")}</button>
          {examples.map((ex) => <button key={ex} type="button" className="secondary" onClick={() => setMessage(ex)}>{ex}</button>)}
        </div>
      </form>
      <div aria-live="polite">
        {error && <p className="notice error">{error}</p>}
        {result && <ResultView result={result} />}
      </div>
    </section>
  );
}

function ResultView({ result }: { result: AssistResult }) {
  const { t } = useI18n();
  const known = KIND_MESSAGES[result.kind];
  switch (result.kind) {
    case "answer":
      return result.answer ? <AnswerView answer={result.answer} /> : null;
    case "navigate": {
      const target = result.target ?? "/offers";
      const screen = SCREENS.find((s) => s.path === target);
      return (
        <p className="notice info">
          {t("assistant.operation")} <Link to={target}>{t("assistant.goTo", { screen: screen ? t(screen.label) : target })}</Link>.
        </p>
      );
    }
    case "agent_run":
      return result.run_id ? <RunView runId={result.run_id} /> : null;
    default:
      return <p className={`notice ${result.kind === "clarify" ? "warn" : "info"}`}>{known ? t(known) : result.message}</p>;
  }
}

function RunView({ runId }: { runId: string }) {
  const { t, label } = useI18n();
  const [run, setRun] = useState<AgentRun | null>(null);
  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    const refresh = () => api<AgentRun>(`/agent-runs/${runId}`).then((r) => {
      if (active) {
        setRun(r);
      }
      return r;
    });
    void refresh();
    void (async () => {
      const { realtimeUrl, realtimeMode } = config();
      if (realtimeMode === "negotiate") {
        // A 503 (not configured) or 404 just leaves the polling below in charge.
        const negotiated = await openNegotiatedRunSocket(() => api<{ url: string }>(`/agent-runs/${runId}/realtime`)).catch(() => null);
        if (!negotiated) return;
        if (!active) return negotiated.close();
        socket = negotiated;
        socket.onmessage = () => void refresh();
        return;
      }
      const token = await currentToken();
      const tenant = selectedTenant.get();
      if (!active || !realtimeUrl || !token || !tenant) return;
      socket = openRunSocket(realtimeUrl, token, tenant, runId);
      socket.onmessage = () => void refresh();
    })();
    // WebSocket events provide immediate updates; polling is a recovery path for missed
    // disconnect events, sleeping browsers and local development without a socket API.
    const id = setInterval(() => void refresh(), 5000);
    return () => {
      active = false;
      clearInterval(id);
      socket?.close();
    };
  }, [runId]);

  return (
    <article className="card stack" aria-label={t("run.label")}>
      <span className="ai-label">{t("ai.toCheck")}</span>
      <p>{t("run.status")} <span className="chip">{label("runStatus", run?.status ?? "queued")}</span></p>
      {run && (
        <>
          <ol>{run.steps.map((s) => <li key={s.seq}>{s.agent} — {label("runStatus", s.status)}</li>)}</ol>
          <p className="muted">{t("run.budget", {
            steps: `${run.steps_used}/${run.max_steps}`,
            tokens: `${run.tokens_used.toLocaleString()}/${run.max_tokens.toLocaleString()}`,
          })}</p>
          {run.findings.filter((f) => f.startsWith("summary:")).map((f) => <p key={f}><strong>{f.slice(8)}</strong></p>)}
        </>
      )}
      <p className="muted">{t("run.disclaimer")}</p>
    </article>
  );
}
