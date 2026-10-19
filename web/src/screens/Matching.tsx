import { useCallback, useEffect, useState } from "react";
import { api, ApiError, post, type MatchingRun, type Proposal, type Satisfied, type Volunteer } from "../api";
import { dateTime, kg, timeRange } from "../format";
import { useI18n } from "../i18n";

const REJECT_REASONS = ["wrong_centre", "timing", "capacity", "quality_concern", "other"];
const LIMITS = [2, 5, 10, 30];

/** FR-020..FR-022: the optimiser proposes, a coordinator decides. Approval confirms the exact content hash. */
export function Matching() {
  const { t, label, locale, errorText } = useI18n();
  const [runs, setRuns] = useState<MatchingRun[] | null>(null);
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [volunteers, setVolunteers] = useState<Volunteer[]>([]);
  const [limit, setLimit] = useState(5);
  const [message, setMessage] = useState<{ kind: "ok" | "error" | "info"; text: string } | null>(null);

  const load = useCallback(async () => {
    const [r, p, v] = await Promise.all([
      api<MatchingRun[]>("/matching-runs").catch(() => []),
      api<Proposal[]>("/proposals").catch(() => []),
      api<Volunteer[]>("/volunteers").catch(() => []),
    ]);
    setRuns(r);
    setProposals(p);
    setVolunteers(v);
    return r;
  }, []);

  const latest = runs?.[0];
  const isRunning = latest?.status === "queued" || latest?.status === "running";

  useEffect(() => {
    void load();
  }, [load]);

  // While the solver works, refresh until the run settles (no websocket needed for a few seconds).
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => void load(), 2000);
    return () => clearInterval(id);
  }, [isRunning, load]);

  async function start() {
    try {
      await post("/matching-runs", { time_limit_seconds: limit });
      setMessage({ kind: "info", text: t("matching.started") });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError && e.status === 429 ? t("matching.busy") : errorText(e, "common.failed") });
    }
    await load();
  }

  return (
    <section aria-labelledby="matching-title" className="stack">
      <h1 id="matching-title">{t("matching.title")}</h1>
      <p className="muted">{t("matching.intro")}</p>
      <div className="card toolbar">
        <label className="inline">
          {t("matching.timeLimit")}{" "}
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            {LIMITS.map((s) => <option key={s} value={s}>{t("matching.seconds", { seconds: String(s) })}</option>)}
          </select>
        </label>
        <button onClick={() => void start()} disabled={isRunning}>{t(isRunning ? "matching.running" : "matching.run")}</button>
      </div>
      <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>

      {latest && (
        <article className="card" aria-label={t("matching.lastRun")}>
          <h2>{t("matching.lastRun")}</h2>
          <p>
            <span className="chip">{label("matchingStatus", latest.status)}</span> {dateTime(latest.created_at, locale)}
            {latest.stats.offers !== undefined && <> · {t("matching.runSummary", {
              offers: String(latest.stats.offers), centres: String(latest.stats.centres ?? 0),
              proposals: String(latest.stats.proposals ?? 0),
            })}</>}
          </p>
          {latest.input_sha256 && <p className="hint">{t("matching.reproducible", { hash: latest.input_sha256.slice(0, 12) })}</p>}
          {(latest.stats.unassigned?.length ?? 0) > 0 && (
            <>
              <h3>{t("matching.unassigned")}</h3>
              <p className="muted">{t("matching.unassignedHint")}</p>
              <ul>
                {latest.stats.unassigned!.map((u) => (
                  <li key={u.offer_id}>
                    {label("category", u.category)} · {kg(u.quantity, locale)} {label("unit", u.unit)}:{" "}
                    {u.reasons.map((r) => label("unassigned", r)).join("; ")}
                  </li>
                ))}
              </ul>
            </>
          )}
        </article>
      )}

      <h2>{t("matching.proposals")}</h2>
      {proposals === null ? <p aria-busy="true">{t("app.loading")}</p> : proposals.length === 0 ? (
        <p className="notice info">{t("matching.noProposals")}</p>
      ) : (
        <>
          {volunteers.length === 0 && <p className="notice warn">{t("matching.noVolunteers")}</p>}
          {proposals.map((p) => (
            <ProposalCard key={p.id} proposal={p} volunteers={volunteers} onDone={(text, kind) => {
              setMessage({ kind, text });
              void load();
            }} />
          ))}
        </>
      )}
    </section>
  );
}

function ProposalCard({ proposal, volunteers, onDone }: {
  proposal: Proposal; volunteers: Volunteer[]; onDone: (text: string, kind: "ok" | "error") => void;
}) {
  const { t, label, locale, errorText } = useI18n();
  const [centre, setCentre] = useState(proposal.center_id);
  const [volunteer, setVolunteer] = useState(volunteers[0]?.membership_id ?? "");
  const [reason, setReason] = useState(REJECT_REASONS[0]);
  const [busy, setBusy] = useState(false);
  const alternative = proposal.alternatives.find((a) => a.center_id === centre);
  const km = (value: number | string | null) => value === null ? t("common.unknown") : t("common.km", { km: kg(value, locale) });

  useEffect(() => {
    if (!volunteer && volunteers[0]) setVolunteer(volunteers[0].membership_id);
  }, [volunteers, volunteer]);

  async function decide(approve: boolean) {
    setBusy(true);
    try {
      await post(`/proposals/${proposal.id}/decision`, approve
        ? { approve, content_sha256: proposal.content_sha256, volunteer_membership_id: volunteer,
            ...(centre !== proposal.center_id ? { center_id: centre } : {}) }
        : { approve, content_sha256: proposal.content_sha256, reason });
      onDone(t(approve ? "matching.approved" : "matching.rejected"), "ok");
    } catch (e) {
      onDone(e instanceof ApiError && e.status === 409 ? t("matching.conflict") : errorText(e, "common.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card stack" aria-label={`${label("category", proposal.category)} → ${proposal.center_name}`}>
      <span className="ai-label">{t("matching.generated")}</span>
      <div className="grid-2">
        <dl className="facts">
          <dt>{t("matching.offer")}</dt>
          <dd>{label("category", proposal.category)} · {kg(proposal.quantity, locale)} {label("unit", proposal.unit)} ·{" "}
            {label("storage", proposal.storage)}</dd>
          <dd className="hint">{label("dateKind", proposal.date_kind)} {new Date(proposal.expires_on).toLocaleDateString(locale)}</dd>
          <dt>{t("matching.donor")}</dt><dd>{proposal.donor_name}</dd>
          <dt>{t("matching.pickup")}</dt><dd>{timeRange(proposal.pickup_from, proposal.pickup_until, locale)}</dd>
        </dl>
        <dl className="facts">
          <dt>{t("matching.centre")}</dt><dd>{alternative?.center_name ?? proposal.center_name}</dd>
          <dt>{t("matching.delivery")}</dt>
          <dd>{timeRange(alternative?.deliver_after ?? proposal.deliver_after, alternative?.deliver_before ?? proposal.deliver_before, locale)}</dd>
          <dt>{t("matching.distance")}</dt><dd>{km(alternative ? alternative.distance_km : proposal.distance_km)}</dd>
        </dl>
      </div>
      <details>
        <summary>{t("matching.why")}</summary>
        <ul>{proposal.explanation.satisfied.map((s) => <li key={s.code}>{explain(s)}</li>)}</ul>
      </details>
      <div className="grid-2">
        <div>
          <label htmlFor={`centre-${proposal.id}`}>{t("matching.chooseCentre")}</label>
          <select id={`centre-${proposal.id}`} value={centre} onChange={(e) => setCentre(e.target.value)}>
            <option value={proposal.center_id}>{t("matching.proposed", { name: proposal.center_name })}</option>
            {proposal.alternatives.map((a) => (
              <option key={a.center_id} value={a.center_id}>{t("matching.alternative", { name: a.center_name, km: km(a.distance_km) })}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`volunteer-${proposal.id}`}>{t("matching.volunteer")}</label>
          <select id={`volunteer-${proposal.id}`} value={volunteer} onChange={(e) => setVolunteer(e.target.value)}
                  disabled={volunteers.length === 0}>
            {volunteers.map((v) => (
              <option key={v.membership_id} value={v.membership_id}>
                {t("matching.openMissions", { name: v.display_name, count: String(v.open_missions) })}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="toolbar">
        <button onClick={() => void decide(true)} disabled={busy || !volunteer}>{t("matching.approve")}</button>
        <label className="inline">
          <span className="visually-hidden">{t("matching.rejectReason")}</span>
          <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label={t("matching.rejectReason")}>
            {REJECT_REASONS.map((r) => <option key={r} value={r}>{label("reason", r)}</option>)}
          </select>
        </label>
        <button className="danger" onClick={() => void decide(false)} disabled={busy}>{t("matching.reject")}</button>
      </div>
    </article>
  );

  function explain(s: Satisfied): string {
    switch (s.code) {
      case "category_accepted":
        return t("why.category_accepted", { value: label("category", s.value) });
      case "storage":
        return t("why.storage", { value: label("storage", s.value) });
      case "slot":
        return t("why.slot", { window: timeRange(s.from, s.until, locale) });
      case "expiry":
        return t("why.expiry", { kind: label("dateKind", s.kind), limit: new Date(s.limit).toLocaleDateString(locale) });
      case "capacity":
        return t("why.capacity", { load: kg(s.load_kg, locale), remaining: kg(s.remaining_kg, locale), capacity: kg(s.capacity_kg, locale) });
      case "distance":
        return s.km === null ? t("why.distanceUnknown") : t("why.distance", { km: t("common.km", { km: kg(s.km, locale) }) });
    }
  }
}
