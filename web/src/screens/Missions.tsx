import { useCallback, useEffect, useState } from "react";
import { api, ApiError, idempotencyKey, type Mission, type MissionChanged, type Volunteer } from "../api";
import { kg, timeRange } from "../format";
import { useI18n } from "../i18n";

const STATUSES = ["assigned", "accepted", "picked_up", "delivered", "failed", "cancelled"];
const FAILURE_REASONS = ["donor_absent", "vehicle_issue", "quality_rejected", "cold_chain_broken", "center_closed", "safety", "other"];
const CANCEL_REASONS = ["no_longer_needed", "offer_withdrawn", "duplicate", "other"];

type Props = { manage: boolean };

/** FR-023/FR-025/FR-027: volunteers move their own missions forward; operators reassign or cancel. */
export function Missions({ manage }: Props) {
  const { t, label } = useI18n();
  const [missions, setMissions] = useState<Mission[] | null>(null);
  const [volunteers, setVolunteers] = useState<Volunteer[]>([]);
  const [status, setStatus] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Mission[]>(`/missions${status ? `?status=${status}` : ""}`).then(setMissions).catch(() => setMissions([]));
    if (manage) api<Volunteer[]>("/volunteers").then(setVolunteers).catch(() => setVolunteers([]));
  }, [status, manage]);
  useEffect(load, [load]);

  const done = (text: string, kind: "ok" | "error") => {
    setMessage({ kind, text });
    load();
  };

  return (
    <section aria-labelledby="missions-title" className="stack">
      <div className="toolbar">
        <h1 id="missions-title">{t(manage ? "missions.title" : "missions.mine")}</h1>
        <label className="inline">
          {t("missions.filter")}{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("missions.all")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{label("missionStatus", s)}</option>)}
          </select>
        </label>
      </div>
      <p className="muted">{t(manage ? "missions.manageIntro" : "missions.intro")}</p>
      <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>
      {missions === null ? <p aria-busy="true">{t("app.loading")}</p> : missions.length === 0 ? (
        <p className="notice info">{t("missions.none")}</p>
      ) : (
        missions.map((m) => <MissionCard key={m.id} mission={m} manage={manage} volunteers={volunteers} onDone={done} />)
      )}
    </section>
  );
}

function MissionCard({ mission, manage, volunteers, onDone }: {
  mission: Mission; manage: boolean; volunteers: Volunteer[]; onDone: (text: string, kind: "ok" | "error") => void;
}) {
  const { t, label, locale, errorText } = useI18n();
  const [action, setAction] = useState<"fail" | "decline" | "cancel" | "reassign" | null>(null);
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(path: string, body: object, withKey: boolean) {
    setBusy(true);
    try {
      // One key per click: a retry of the same click after a network error is applied once (FR-027).
      const headers = withKey ? { "Idempotency-Key": idempotencyKey() } : undefined;
      await api<MissionChanged>(path, { method: "POST", body: JSON.stringify(body), headers });
      setAction(null);
      onDone(t("missions.done"), "ok");
    } catch (e) {
      onDone(e instanceof ApiError && e.status === 409 ? t("missions.conflict") : errorText(e, "missions.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  const move = (to: string, why?: string) =>
    send(`/missions/${mission.id}/transition`, { to, version: mission.version, ...(why ? { reason: why } : {}) }, true);

  const volunteerActions = !manage && mission.assigned_to_me;
  const open = ["assigned", "accepted", "failed"].includes(mission.status) && mission.picked_up_at === null;
  const map = mission.donor_latitude !== null && mission.donor_longitude !== null
    ? `https://www.openstreetmap.org/?mlat=${mission.donor_latitude}&mlon=${mission.donor_longitude}#map=16/${mission.donor_latitude}/${mission.donor_longitude}`
    : null;

  return (
    <article className="card stack" aria-label={`${label("category", mission.category)} · ${mission.center_name}`}>
      <div className="toolbar">
        <strong>{label("category", mission.category)} · {kg(mission.quantity, locale)} {label("unit", mission.unit)} · {label("storage", mission.storage)}</strong>
        <span className="chip">{label("missionStatus", mission.status)}</span>
      </div>
      <div className="grid-2">
        <dl className="facts">
          <dt>{t("missions.pickupAt", { donor: mission.donor_name })}</dt>
          <dd>{timeRange(mission.pickup_from, mission.pickup_until, locale)}</dd>
          {map && <dd><a href={map} target="_blank" rel="noreferrer">{t("missions.map")}</a></dd>}
        </dl>
        <dl className="facts">
          <dt>{t("missions.deliverTo", { centre: mission.center_name })}</dt>
          <dd>{timeRange(mission.deliver_after, mission.deliver_before, locale)}</dd>
          {mission.center_address && <dd className="hint">{mission.center_address}</dd>}
        </dl>
      </div>
      <p className="hint">
        {label("dateKind", mission.date_kind)} {new Date(mission.expires_on).toLocaleDateString(locale)}
        {manage && mission.volunteer_name && <> · {t("missions.volunteer")}: {mission.volunteer_name}</>}
        {mission.reassignments > 0 && <> · {t("missions.reassignments", { count: String(mission.reassignments) })}</>}
        {mission.failure_reason && <> · {label("reason", mission.failure_reason)}</>}
        {mission.receipt && <> · {t("missions.receipt")}: {label("receipt", mission.receipt)}
          {mission.received_quantity !== null && <> ({t("missions.received", { quantity: kg(mission.received_quantity, locale) })})</>}</>}
      </p>

      {volunteerActions && (
        <div className="toolbar">
          {mission.status === "assigned" && <>
            <button onClick={() => void move("accepted")} disabled={busy}>{t("missions.accept")}</button>
            <button className="secondary" onClick={() => void move("failed", "declined")} disabled={busy}>{t("missions.decline")}</button>
          </>}
          {mission.status === "accepted" && <button onClick={() => void move("picked_up")} disabled={busy}>{t("missions.pickedUp")}</button>}
          {mission.status === "picked_up" && <button onClick={() => void move("delivered")} disabled={busy}>{t("missions.delivered")}</button>}
          {["assigned", "accepted", "picked_up"].includes(mission.status) &&
            <button className="danger" onClick={() => setAction("fail")} disabled={busy}>{t("missions.problem")}</button>}
        </div>
      )}
      {manage && (
        <div className="toolbar">
          {open && <button className="secondary" onClick={() => setAction("reassign")} disabled={busy || volunteers.length === 0}>{t("missions.reassign")}</button>}
          {["assigned", "accepted", "failed", "picked_up"].includes(mission.status) &&
            <button className="danger" onClick={() => setAction("cancel")} disabled={busy}>{t("missions.cancel")}</button>}
        </div>
      )}

      {(action === "fail" || action === "cancel") && (
        <form className="toolbar" onSubmit={(e) => {
          e.preventDefault();
          void move(action === "fail" ? "failed" : "cancelled", reason);
        }}>
          <label className="inline">
            {t("missions.reason")}{" "}
            <select value={reason} onChange={(e) => setReason(e.target.value)} required>
              <option value="" disabled>—</option>
              {(action === "fail" ? FAILURE_REASONS : CANCEL_REASONS).map((r) => <option key={r} value={r}>{label("reason", r)}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy || !reason}>{t("missions.confirm")}</button>
          <button type="button" className="secondary" onClick={() => setAction(null)}>{t("common.cancel")}</button>
        </form>
      )}
      {action === "reassign" && (
        <form className="toolbar" onSubmit={(e) => {
          e.preventDefault();
          void send(`/missions/${mission.id}/reassign`, { volunteer_membership_id: target, version: mission.version }, false);
        }}>
          <label className="inline">
            {t("missions.reassignTo")}{" "}
            <select value={target} onChange={(e) => setTarget(e.target.value)} required>
              <option value="" disabled>—</option>
              {volunteers.map((v) => (
                <option key={v.membership_id} value={v.membership_id}>
                  {t("matching.openMissions", { name: v.display_name, count: String(v.open_missions) })}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy || !target}>{t("missions.confirm")}</button>
          <button type="button" className="secondary" onClick={() => setAction(null)}>{t("common.cancel")}</button>
        </form>
      )}
    </article>
  );
}
