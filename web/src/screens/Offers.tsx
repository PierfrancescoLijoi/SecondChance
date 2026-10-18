import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, post, type Offer } from "../api";
import { useI18n } from "../i18n";

type Props = { canReserve: boolean; isDonor: boolean };

export function Offers({ canReserve, isDonor }: Props) {
  const { t, label, locale } = useI18n();
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Offer[]>("/offers").then(setOffers).catch(() => setOffers([]));
  }, []);
  useEffect(load, [load]);

  async function reserve(offer: Offer) {
    try {
      await post(`/offers/${offer.id}/reserve`, { version: offer.version });
      setMessage({ kind: "ok", text: t("offers.reserved") });
    } catch (e) {
      const isConflict = e instanceof ApiError && e.status === 409;
      setMessage({ kind: "error", text: t(isConflict ? "offers.conflict" : "offers.reserveFailed") });
    }
    load();
  }

  return (
    <section aria-labelledby="offers-title" className="stack">
      <h1 id="offers-title">{t(isDonor ? "offers.mine" : "offers.network")}</h1>
      {isDonor && <p><Link className="button" to="/offers/new">{t("offers.publishNew")}</Link></p>}
      <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>
      {offers === null ? (
        <p aria-busy="true">{t("app.loading")}</p>
      ) : offers.length === 0 ? (
        <p className="notice info">{t("offers.none")}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">{t("offers.caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("offers.category")}</th><th scope="col">{t("offers.quantity")}</th>
                <th scope="col">{t("offers.expiry")}</th><th scope="col">{t("offers.storage")}</th>
                <th scope="col">{t("offers.status")}</th>{canReserve && <th scope="col">{t("offers.action")}</th>}
              </tr>
            </thead>
            <tbody>
              {offers.map((offer) => (
                <tr key={offer.id}>
                  <td>{label("category", offer.category)}</td>
                  <td>{Number(offer.quantity).toLocaleString(locale)} {label("unit", offer.unit)}</td>
                  <td>
                    {new Date(offer.expires_on).toLocaleDateString(locale)}{" "}
                    <span className="hint">({label("dateKind", offer.date_kind)})</span>
                  </td>
                  <td>{label("storage", offer.storage)}</td>
                  <td><span className="chip">{label("status", offer.status)}</span></td>
                  {canReserve && (
                    <td>{offer.status === "available" && <button onClick={() => void reserve(offer)}>{t("offers.reserve")}</button>}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
