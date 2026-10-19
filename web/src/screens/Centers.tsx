import { useCallback, useEffect, useState } from "react";
import { api, ApiError, post, type Center, type Mission, type Slot, type Versioned } from "../api";
import { hhmm, kg, timeRange, weekdayName } from "../format";
import { useI18n } from "../i18n";

const CATEGORIES = ["dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals", "beverages", "other"];
const STORAGE = ["ambient", "chilled", "frozen"];
const EXCEPTION_REASONS = ["partial", "quality_rejected", "cold_chain_broken", "damaged", "wrong_items", "other"];
const BLANK: Omit<Center, "id" | "version" | "updated_at" | "committed_today_kg" | "slots"> = {
  name: "", status: "active", address: null, latitude: null, longitude: null,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  accepted_categories: [...CATEGORIES], storage_capabilities: ["ambient"], daily_capacity_kg: "200",
};

type Props = {
  /** Centre staff: their own centre only. */
  own?: boolean;
  /** Org admins create and edit every centre; coordinators read. */
  canManage: boolean;
  canCreate?: boolean;
};

/** FR-003/FR-014: capacity, accepted food, storage and opening slots drive what the optimiser may propose. */
export function Centers({ own = false, canManage, canCreate = false }: Props) {
  const { t } = useI18n();
  const [centers, setCenters] = useState<Center[] | null>(null);
  const [selected, setSelected] = useState<string | "new" | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Center[]>("/centers").then((list) => {
      setCenters(list);
      setSelected((current) => current === "new" ? current : current && list.some((c) => c.id === current) ? current : list[0]?.id ?? null);
    }).catch(() => setCenters([]));
  }, []);
  useEffect(load, [load]);

  const notify = (text: string, kind: "ok" | "error") => {
    setMessage({ kind, text });
    load();
  };
  const center = centers?.find((c) => c.id === selected) ?? null;

  return (
    <section aria-labelledby="centers-title" className="stack">
      <h1 id="centers-title">{t(own ? "center.title" : "centers.title")}</h1>
      <p className="muted">{t("center.intro")}</p>
      <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>
      {centers === null ? <p aria-busy="true">{t("app.loading")}</p> : (
        <>
          {centers.length === 0 && own && <p className="notice warn">{t("center.none")}</p>}
          {!own && (centers.length > 0 || canCreate) && (
            <div className="toolbar">
              {centers.length > 0 && (
                <label className="inline">
                  {t("center.select")}{" "}
                  <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value)}>
                    {centers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    {selected === "new" && <option value="new">{t("center.new")}</option>}
                  </select>
                </label>
              )}
              {canCreate && <button className="secondary" onClick={() => setSelected("new")}>{t("center.new")}</button>}
            </div>
          )}
          {selected === "new" && canCreate && <CenterForm key="new" onDone={notify} />}
          {center && (
            <>
              <CenterForm key={`${center.id}-${center.version}`} center={center} readOnly={!canManage} onDone={notify} />
              <SlotsEditor key={`slots-${center.id}-${center.version}`} center={center} readOnly={!canManage} onDone={notify} />
              <Deliveries centerId={center.id} canConfirm={own || canManage} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function CenterForm({ center, readOnly = false, onDone }: {
  center?: Center; readOnly?: boolean; onDone: (text: string, kind: "ok" | "error") => void;
}) {
  const { t, label, locale, errorText } = useI18n();
  const [values, setValues] = useState(center ?? { ...BLANK });
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof typeof values>(key: K, value: (typeof values)[K]) => setValues((v) => ({ ...v, [key]: value }));
  const toggle = (key: "accepted_categories" | "storage_capabilities", item: string) =>
    set(key, values[key].includes(item) ? values[key].filter((x) => x !== item) : [...values[key], item]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    const body = {
      name: values.name, status: values.status, address: values.address || null,
      latitude: values.latitude === null || String(values.latitude) === "" ? null : Number(values.latitude),
      longitude: values.longitude === null || String(values.longitude) === "" ? null : Number(values.longitude),
      timezone: values.timezone, accepted_categories: values.accepted_categories,
      storage_capabilities: values.storage_capabilities, daily_capacity_kg: Number(values.daily_capacity_kg),
    };
    try {
      if (center) await post<Versioned>(`/centers/${center.id}`, { ...body, version: center.version });
      else await post<Versioned>("/centers", body);
      onDone(t(center ? "common.saved" : "center.created"), "ok");
    } catch (e) {
      onDone(e instanceof ApiError && e.status === 409 ? t("common.conflict") : errorText(e, "common.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={(e) => void save(e)} aria-label={center?.name ?? t("center.new")}>
      <h2>{center?.name ?? t("center.new")}</h2>
      {center && (
        <p>
          <meter min={0} max={Number(center.daily_capacity_kg)} value={Number(center.committed_today_kg)} aria-hidden="true" />{" "}
          {t("center.committedToday", { kg: kg(center.committed_today_kg, locale), capacity: kg(center.daily_capacity_kg, locale) })}
        </p>
      )}
      {readOnly && <p className="notice info">{t("center.readOnly")}</p>}
      <fieldset disabled={readOnly || busy} className="plain-fieldset stack">
        <div className="grid-2">
          <div>
            <label htmlFor="center-name">{t("center.name")}</label>
            <input id="center-name" value={values.name} onChange={(e) => set("name", e.target.value)} minLength={2} maxLength={120} required />
          </div>
          <div>
            <label htmlFor="center-status">{t("center.status")}</label>
            <select id="center-status" value={values.status} onChange={(e) => set("status", e.target.value as Center["status"])}>
              {["active", "paused"].map((s) => <option key={s} value={s}>{label("centerStatus", s)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="center-capacity">{t("center.capacity")}</label>
            <input id="center-capacity" type="number" min="1" step="0.01" value={values.daily_capacity_kg}
                   onChange={(e) => set("daily_capacity_kg", e.target.value)} required />
          </div>
          <div>
            <label htmlFor="center-timezone">{t("center.timezone")}</label>
            <input id="center-timezone" value={values.timezone} onChange={(e) => set("timezone", e.target.value)} required />
          </div>
          <div>
            <label htmlFor="center-address">{t("center.address")}</label>
            <input id="center-address" value={values.address ?? ""} onChange={(e) => set("address", e.target.value)} maxLength={200} />
          </div>
          <div className="grid-2">
            <div>
              <label htmlFor="center-lat">{t("center.latitude")}</label>
              <input id="center-lat" type="number" step="any" min="-90" max="90" value={values.latitude ?? ""}
                     onChange={(e) => set("latitude", e.target.value === "" ? null : Number(e.target.value))} />
            </div>
            <div>
              <label htmlFor="center-lon">{t("center.longitude")}</label>
              <input id="center-lon" type="number" step="any" min="-180" max="180" value={values.longitude ?? ""}
                     onChange={(e) => set("longitude", e.target.value === "" ? null : Number(e.target.value))} />
            </div>
          </div>
        </div>
        <fieldset>
          <legend>{t("center.categories")}</legend>
          <div className="checks">
            {CATEGORIES.map((c) => (
              <label key={c} className="radio">
                <input type="checkbox" checked={values.accepted_categories.includes(c)} onChange={() => toggle("accepted_categories", c)} />
                {label("category", c)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>{t("center.storage")}</legend>
          <div className="checks">
            {STORAGE.map((s) => (
              <label key={s} className="radio">
                <input type="checkbox" checked={values.storage_capabilities.includes(s)} onChange={() => toggle("storage_capabilities", s)} />
                {label("storage", s)}
              </label>
            ))}
          </div>
        </fieldset>
        {!readOnly && (
          <button type="submit" disabled={values.accepted_categories.length === 0 || values.storage_capabilities.length === 0}>
            {t(center ? "common.save" : "center.create")}
          </button>
        )}
      </fieldset>
    </form>
  );
}

function SlotsEditor({ center, readOnly, onDone }: {
  center: Center; readOnly: boolean; onDone: (text: string, kind: "ok" | "error") => void;
}) {
  const { t, locale, errorText } = useI18n();
  const [slots, setSlots] = useState<Slot[]>(center.slots.map((s) => ({ ...s, opens: hhmm(s.opens), closes: hhmm(s.closes) })));
  const [busy, setBusy] = useState(false);
  const update = (index: number, patch: Partial<Slot>) => setSlots((all) => all.map((s, i) => (i === index ? { ...s, ...patch } : s)));

  async function save() {
    setBusy(true);
    try {
      await post<Versioned>(`/centers/${center.id}/slots`, { version: center.version, slots });
      onDone(t("common.saved"), "ok");
    } catch (e) {
      onDone(e instanceof ApiError && e.status === 409 ? t("common.conflict") : errorText(e, "common.failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card stack" aria-label={t("center.slots")}>
      <h2>{t("center.slots")}</h2>
      <p className="muted">{t("center.slotsHint")}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">{t("center.day")}</th><th scope="col">{t("center.opens")}</th><th scope="col">{t("center.closes")}</th>
              {!readOnly && <th scope="col"><span className="visually-hidden">{t("center.removeSlot")}</span></th>}</tr>
          </thead>
          <tbody>
            {slots.map((slot, i) => (
              <tr key={i}>
                <td>
                  <select aria-label={t("center.day")} value={slot.weekday} disabled={readOnly}
                          onChange={(e) => update(i, { weekday: Number(e.target.value) })}>
                    {[1, 2, 3, 4, 5, 6, 7].map((d) => <option key={d} value={d}>{weekdayName(d, locale)}</option>)}
                  </select>
                </td>
                <td><input aria-label={t("center.opens")} type="time" value={slot.opens} disabled={readOnly}
                           onChange={(e) => update(i, { opens: e.target.value })} /></td>
                <td><input aria-label={t("center.closes")} type="time" value={slot.closes} disabled={readOnly}
                           onChange={(e) => update(i, { closes: e.target.value })} /></td>
                {!readOnly && <td><button type="button" className="danger" onClick={() => setSlots((all) => all.filter((_, j) => j !== i))}>
                  {t("center.removeSlot")}</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!readOnly && (
        <div className="toolbar">
          <button type="button" className="secondary" disabled={slots.length >= 28}
                  onClick={() => setSlots((all) => [...all, { weekday: 1, opens: "09:00", closes: "17:00" }])}>{t("center.addSlot")}</button>
          <button type="button" onClick={() => void save()} disabled={busy}>{t("center.saveSlots")}</button>
        </div>
      )}
    </article>
  );
}

function Deliveries({ centerId, canConfirm }: { centerId: string; canConfirm: boolean }) {
  const { t, label, locale, errorText } = useI18n();
  const [missions, setMissions] = useState<Mission[] | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const load = useCallback(() => {
    api<Mission[]>(`/centers/${centerId}/deliveries`).then(setMissions).catch(() => setMissions([]));
  }, [centerId]);
  useEffect(load, [load]);

  async function receipt(mission: Mission, outcome: "confirmed" | "exception", quantity: string, reason: string) {
    try {
      await post(`/missions/${mission.id}/receipt`, {
        outcome, version: mission.version, received_quantity: Number(quantity), ...(outcome === "exception" ? { reason } : {}),
      });
      setMessage({ kind: "ok", text: t("common.saved") });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError && e.status === 409 ? t("missions.conflict") : errorText(e, "common.failed") });
    }
    load();
  }

  const live = missions?.filter((m) => !["cancelled"].includes(m.status)) ?? [];
  return (
    <article className="card stack" aria-label={t("center.deliveries")}>
      <h2>{t("center.deliveries")}</h2>
      <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>
      {missions === null ? <p aria-busy="true">{t("app.loading")}</p> : live.length === 0 ? (
        <p className="muted">{t("center.noDeliveries")}</p>
      ) : (
        <ul className="plain stack">
          {live.map((m) => (
            <li key={m.id} className="delivery">
              <p>
                <strong>{label("category", m.category)} · {kg(m.quantity, locale)} {label("unit", m.unit)}</strong>{" "}
                <span className="chip">{label("missionStatus", m.status)}</span>
              </p>
              <p className="hint">{timeRange(m.deliver_after, m.deliver_before, locale)} · {m.donor_name}
                {m.receipt && <> · {t("missions.receipt")}: {label("receipt", m.receipt)}</>}</p>
              {canConfirm && !m.receipt && ["picked_up", "delivered"].includes(m.status) && (
                <ReceiptForm mission={m} onSubmit={receipt} />
              )}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function ReceiptForm({ mission, onSubmit }: {
  mission: Mission; onSubmit: (m: Mission, outcome: "confirmed" | "exception", quantity: string, reason: string) => Promise<void>;
}) {
  const { t, label } = useI18n();
  const [quantity, setQuantity] = useState(mission.quantity);
  const [reason, setReason] = useState(EXCEPTION_REASONS[0]);
  const [busy, setBusy] = useState(false);
  const run = async (outcome: "confirmed" | "exception") => {
    setBusy(true);
    await onSubmit(mission, outcome, quantity, reason);
    setBusy(false);
  };
  return (
    <div className="toolbar">
      <label className="inline">
        {t("center.receivedQuantity")}{" "}
        <input type="number" min="0" max={mission.quantity} step="0.001" value={quantity} onChange={(e) => setQuantity(e.target.value)}
               style={{ width: "8rem" }} />
      </label>
      <button onClick={() => void run("confirmed")} disabled={busy || !(Number(quantity) > 0)}>{t("center.confirmReceipt")}</button>
      <select aria-label={t("missions.reason")} value={reason} onChange={(e) => setReason(e.target.value)}>
        {EXCEPTION_REASONS.map((r) => <option key={r} value={r}>{label("reason", r)}</option>)}
      </select>
      <button className="danger" onClick={() => void run("exception")} disabled={busy}>{t("center.exception")}</button>
    </div>
  );
}
