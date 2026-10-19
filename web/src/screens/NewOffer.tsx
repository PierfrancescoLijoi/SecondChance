import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { post } from "../api";
import { useI18n } from "../i18n";
import type { MessageKey } from "../locales/en";

const CATEGORIES = ["dairy", "meat_fish", "fruit_vegetables", "bakery", "dry_goods", "frozen", "ready_meals", "beverages", "other"];
const STORAGE = ["ambient", "chilled", "frozen"];
const UNITS = ["kg", "l", "pcs"];

/** Same rules as the API schema, checked before sending: errors appear at once (ADR-016). */
export function validateOffer(values: Record<string, string>, today = new Date()): MessageKey | null {
  const quantity = Number(values.quantity);
  if (!(quantity > 0 && quantity <= 100000)) return "offerError.quantity";
  const start = new Date(values.pickup_from);
  const end = new Date(values.pickup_until);
  if (!(end > start)) return "offerError.window";
  if (end.getTime() - start.getTime() > 14 * 86400000) return "offerError.windowTooLong";
  const isoToday = today.toISOString().slice(0, 10);
  if (values.date_kind === "use_by" && values.expires_on < isoToday) return "offerError.useByPassed";
  return null;
}

export function NewOffer() {
  const { t, label, errorText } = useI18n();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget)) as Record<string, string>;
    const problem = validateOffer(values);
    if (problem) return setError(t(problem));
    try {
      await post("/offers", {
        ...values,
        pickup_from: new Date(values.pickup_from).toISOString(),
        pickup_until: new Date(values.pickup_until).toISOString(),
      });
      navigate("/offers");
    } catch (e) {
      setError(errorText(e, "newOffer.failed"));
    }
  }

  return (
    <section aria-labelledby="new-offer-title">
      <h1 id="new-offer-title">{t("newOffer.title")}</h1>
      <form className="card stack" onSubmit={(e) => void handleSubmit(e)} noValidate>
        <div aria-live="assertive">{error && <p className="notice error">{error}</p>}</div>
        <div className="grid-2">
          <div>
            <label htmlFor="category">{t("offers.category")}</label>
            <select id="category" name="category" required>
              {CATEGORIES.map((v) => <option key={v} value={v}>{label("category", v)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="storage">{t("offers.storage")}</label>
            <select id="storage" name="storage" required>
              {STORAGE.map((v) => <option key={v} value={v}>{label("storage", v)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="quantity">{t("offers.quantity")}</label>
            <input id="quantity" name="quantity" type="number" min="0.001" step="0.001" required />
          </div>
          <div>
            <label htmlFor="unit">{t("newOffer.unit")}</label>
            <select id="unit" name="unit">{UNITS.map((v) => <option key={v} value={v}>{label("unit", v)}</option>)}</select>
          </div>
        </div>
        <fieldset>
          <legend>{t("newOffer.dateKind")}</legend>
          <label className="radio">
            <input type="radio" name="date_kind" value="use_by" defaultChecked />{" "}
            <span><strong>{t("dateKind.use_by")}</strong> — {t("newOffer.useByHint")}</span>
          </label>
          <label className="radio">
            <input type="radio" name="date_kind" value="best_before" />{" "}
            <span><strong>{t("dateKind.best_before")}</strong> — {t("newOffer.bestBeforeHint")}</span>
          </label>
        </fieldset>
        <div className="grid-2">
          <div><label htmlFor="expires_on">{t("newOffer.expiresOn")}</label><input id="expires_on" name="expires_on" type="date" required /></div>
          <div />
          <div><label htmlFor="pickup_from">{t("newOffer.pickupFrom")}</label><input id="pickup_from" name="pickup_from" type="datetime-local" required /></div>
          <div><label htmlFor="pickup_until">{t("newOffer.pickupUntil")}</label><input id="pickup_until" name="pickup_until" type="datetime-local" required /></div>
        </div>
        <button type="submit">{t("newOffer.submit")}</button>
      </form>
    </section>
  );
}
