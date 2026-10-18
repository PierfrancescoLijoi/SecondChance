import { useEffect, useState } from "react";
import { api, post, type Network } from "../api";
import { signOut } from "../auth";
import { useI18n } from "../i18n";

type Kind = "donor" | "ngo";

const DONOR_TYPES = ["supermarket", "restaurant", "canteen", "producer", "wholesaler", "other"];
const COUNTRIES = ["DK", "PL", "IT", "DE", "FR", "ES", "SE", "NL"];

export function Register({ onRegistered }: { onRegistered: () => void }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<Kind | null>(null);
  return (
    <main className="hero" id="content" style={{ display: "block", maxWidth: 760 }}>
      <p className="kicker">{t("register.kicker")}</p>
      <h1>{t("register.title")}</h1>
      <p className="lead">{t("register.lead")}</p>
      <div className="grid-2" role="group" aria-label={t("register.accountType")}>
        <button className="choice" aria-pressed={kind === "donor"} onClick={() => setKind("donor")}>
          <strong>{t("register.donorTitle")}</strong>
          {t("register.donorText")}
        </button>
        <button className="choice" aria-pressed={kind === "ngo"} onClick={() => setKind("ngo")}>
          <strong>{t("register.ngoTitle")}</strong>
          {t("register.ngoText")}
        </button>
      </div>
      {kind && <div className="card" style={{ marginTop: "1.5rem" }}><RegistrationForm kind={kind} onDone={onRegistered} /></div>}
      <p style={{ marginTop: "1rem" }}>
        <button className="secondary" onClick={() => void signOut().then(() => window.location.assign("/"))}>{t("app.signOut")}</button>
      </p>
    </main>
  );
}

function RegistrationForm({ kind, onDone }: { kind: Kind; onDone: () => void }) {
  const { t, label, locale, errorText } = useI18n();
  const [networks, setNetworks] = useState<Network[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const countryName = new Intl.DisplayNames([locale], { type: "region" });

  useEffect(() => {
    if (kind === "donor") api<Network[]>("/networks").then(setNetworks).catch(() => setNetworks([]));
  }, [kind]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body =
      kind === "ngo"
        ? { type: "ngo", organization_name: form.get("name"), country: form.get("country") }
        : { type: "donor", organization_name: form.get("name"), network_id: form.get("network"), donor_type: form.get("donor_type") };
    setIsSending(true);
    try {
      await post("/registrations", body);
      onDone();
    } catch (e) {
      setError(errorText(e, "register.failed"));
    } finally {
      setIsSending(false);
    }
  }

  return (
    <form className="stack" onSubmit={(e) => void handleSubmit(e)}>
      <h2>{kind === "ngo" ? t("register.ngoDetails") : t("register.donorDetails")}</h2>
      {error && <p className="notice error" role="alert">{error}</p>}
      <div>
        <label htmlFor="name">{t("register.name")}</label>
        <input id="name" name="name" minLength={2} maxLength={120} required autoComplete="organization" />
      </div>
      {kind === "ngo" ? (
        <div>
          <label htmlFor="country">{t("register.country")}</label>
          <select id="country" name="country" required>
            {COUNTRIES.map((code) => <option key={code} value={code}>{countryName.of(code)}</option>)}
          </select>
        </div>
      ) : (
        <>
          <div>
            <label htmlFor="network">{t("register.network")} <span className="hint">{t("register.networkHint")}</span></label>
            <select id="network" name="network" required>
              {networks.map((n) => <option key={n.id} value={n.id}>{n.name} ({countryName.of(n.country)})</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="donor_type">{t("register.donorType")}</label>
            <select id="donor_type" name="donor_type" required>
              {DONOR_TYPES.map((value) => <option key={value} value={value}>{label("donorType", value)}</option>)}
            </select>
          </div>
        </>
      )}
      <p className="muted">{t("register.privacy")}</p>
      <button type="submit" disabled={isSending || (kind === "donor" && networks.length === 0)}>{t("register.submit")}</button>
    </form>
  );
}
