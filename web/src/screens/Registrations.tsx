import { useCallback, useEffect, useState } from "react";
import { api, post, type Center, type PendingRegistration } from "../api";
import { useI18n } from "../i18n";

export function Registrations({ platform }: { platform: boolean }) {
  const { t, label, locale, errorText } = useI18n();
  const [items, setItems] = useState<PendingRegistration[] | null>(null);
  const [centers, setCenters] = useState<Center[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const countryName = new Intl.DisplayNames([locale], { type: "region" });

  const load = useCallback(() => {
    api<PendingRegistration[]>("/admin/registrations").then(setItems).catch(() => setItems([]));
    // Centre staff are approved for one centre of the network (ADR-017): the admin picks it.
    if (!platform) api<Center[]>("/centers").then(setCenters).catch(() => setCenters([]));
  }, [platform]);
  useEffect(load, [load]);

  async function decide(item: PendingRegistration, approve: boolean) {
    const centerId = item.role === "center_staff" && approve ? chosen[item.membership_id] ?? centers[0]?.id : undefined;
    try {
      await post(`/admin/registrations/${item.membership_id}/decision`, { approve, ...(centerId ? { center_id: centerId } : {}) });
      setMessage(t(approve ? "registrations.approved" : "registrations.rejected", { name: item.organization_name }));
    } catch (e) {
      setMessage(errorText(e, "registrations.failed"));
    }
    load();
  }

  const describe = (item: PendingRegistration) =>
    item.type === "ngo"
      ? `${t("registrations.ngo")} · ${item.country ? countryName.of(item.country) : ""}`
      : item.type === "member"
        ? label("role", item.role ?? "volunteer")
        : `${t("registrations.donor")} · ${item.donor_type ? label("donorType", item.donor_type) : ""}`;

  return (
    <section aria-labelledby="registrations-title" className="stack">
      <h1 id="registrations-title">{t(platform ? "registrations.platformTitle" : "registrations.networkTitle")}</h1>
      <p className="muted">{t(platform ? "registrations.platformHint" : "registrations.networkHint")}</p>
      <div aria-live="polite">{message && <p className="notice ok">{message}</p>}</div>
      {items === null ? <p aria-busy="true">{t("app.loading")}</p> : items.length === 0 ? (
        <p className="notice info">{t("registrations.none")}</p>
      ) : (
        items.map((item) => (
          <article key={item.membership_id} className="card" aria-label={item.organization_name}>
            <h2>{item.organization_name}</h2>
            <p className="muted">
              {describe(item)} · {t("registrations.requested")} {new Date(item.created_at).toLocaleDateString(locale)}
            </p>
            {item.role === "center_staff" && (
              <div>
                <label htmlFor={`centre-${item.membership_id}`}>{t("registrations.centre")}</label>
                {centers.length === 0 ? <p className="notice warn">{t("registrations.noCentre")}</p> : (
                  <select id={`centre-${item.membership_id}`} value={chosen[item.membership_id] ?? centers[0]?.id}
                          onChange={(e) => setChosen((c) => ({ ...c, [item.membership_id]: e.target.value }))}>
                    {centers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                )}
              </div>
            )}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={() => void decide(item, true)} disabled={item.role === "center_staff" && centers.length === 0}>
                {t("registrations.approve")}
              </button>
              <button className="danger" onClick={() => void decide(item, false)}>{t("registrations.reject")}</button>
            </div>
          </article>
        ))
      )}
    </section>
  );
}
