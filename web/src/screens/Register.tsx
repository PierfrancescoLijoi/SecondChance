import { useEffect, useState } from "react";
import { api, post, type Network } from "../api";
import { signOut } from "../auth";
import { useI18n } from "../i18n";

type Kind = "donor" | "ngo" | "member";

const DONOR_TYPES = ["supermarket", "restaurant", "canteen", "producer", "wholesaler", "other"];
const COUNTRIES = ["DK", "PL", "IT", "DE", "FR", "ES", "SE", "NL"];
const MEMBER_ROLES = ["volunteer", "center_staff", "coordinator"];

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
        <button className="choice" aria-pressed={kind === "member"} onClick={() => setKind("member")}>
          <strong>{t("register.memberTitle")}</strong>
          {t("register.memberText")}
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
    if (kind !== "ngo") api<Network[]>("/networks").then(setNetworks).catch(() => setNetworks([]));
  }, [kind]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body =
      kind === "ngo"
        ? { type: "ngo", organization_name: form.get("name"), country: form.get("country") }
        : kind === "member"
          ? { type: "member", network_id: form.get("network"), role: form.get("role"), display_name: form.get("display_name") }
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
      <h2>{t(kind === "ngo" ? "register.ngoDetails" : kind === "member" ? "register.memberDetails" : "register.donorDetails")}</h2>
      {error && <p className="notice error" role="alert">{error}</p>}
      {kind === "member" ? (
        <>
          <div>
            <label htmlFor="role">{t("register.role")}</label>
            <select id="role" name="role" required>
              {MEMBER_ROLES.map((role) => <option key={role} value={role}>{label("role", role)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="display_name">{t("register.displayName")} <span className="hint">{t("register.displayNameHint")}</span></label>
            <input id="display_name" name="display_name" minLength={1} maxLength={80} required autoComplete="nickname" />
          </div>
          <div>
            <label htmlFor="network">{t("register.memberNetwork")} <span className="hint">{t("register.networkHint")}</span></label>
            <select id="network" name="network" required>
              {networks.map((n) => <option key={n.id} value={n.id}>{n.name} ({countryName.of(n.country)})</option>)}
            </select>
          </div>
        </>
      ) : (
        <div>
          <label htmlFor="name">{t("register.name")}</label>
          <input id="name" name="name" minLength={2} maxLength={120} required autoComplete="organization" />
        </div>
      )}
      {kind === "member" ? null : kind === "ngo" ? (
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
      <p className="muted">{t(kind === "member" ? "register.memberPrivacy" : "register.privacy")}</p>
      <button type="submit" disabled={isSending || (kind !== "ngo" && networks.length === 0)}>{t("register.submit")}</button>
    </form>
  );
}
