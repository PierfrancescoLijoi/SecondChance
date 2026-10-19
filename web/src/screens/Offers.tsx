import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, post, type Offer } from "../api";
import { useI18n } from "../i18n";

type Props = { canReserve: boolean; isDonor: boolean; organizationId?: string | null };

export function Offers({ canReserve, isDonor, organizationId = null }: Props) {
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
      {isDonor && organizationId && <PickupLocation organizationId={organizationId} />}
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

/** Coordinates of the donor's site let the optimiser prefer the nearest centre (organisation data, never a person's). */
function PickupLocation({ organizationId }: { organizationId: string }) {
  const { t, errorText } = useI18n();
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  function locate() {
    navigator.geolocation?.getCurrentPosition((position) => {
      setLatitude(position.coords.latitude.toFixed(5));
      setLongitude(position.coords.longitude.toFixed(5));
    });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post(`/organizations/${organizationId}/location`, { latitude: Number(latitude), longitude: Number(longitude) });
      setMessage({ kind: "ok", text: t("offers.locationSaved") });
    } catch (e) {
      setMessage({ kind: "error", text: errorText(e, "common.failed") });
    }
  }

  return (
    <details className="card">
      <summary>{t("offers.location")}</summary>
      <form className="stack" onSubmit={(e) => void save(e)}>
        <p className="muted">{t("offers.locationHint")}</p>
        <div aria-live="polite">{message && <p className={`notice ${message.kind}`}>{message.text}</p>}</div>
        <div className="grid-2">
          <div>
            <label htmlFor="pickup-lat">{t("center.latitude")}</label>
            <input id="pickup-lat" type="number" step="any" min="-90" max="90" value={latitude} onChange={(e) => setLatitude(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="pickup-lon">{t("center.longitude")}</label>
            <input id="pickup-lon" type="number" step="any" min="-180" max="180" value={longitude} onChange={(e) => setLongitude(e.target.value)} required />
          </div>
        </div>
        <div className="toolbar">
          {"geolocation" in navigator && <button type="button" className="secondary" onClick={locate}>{t("offers.useMyLocation")}</button>}
          <button type="submit">{t("offers.saveLocation")}</button>
        </div>
      </form>
    </details>
  );
}
