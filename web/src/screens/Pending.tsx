import type { Membership } from "../api";
import { signOut } from "../auth";
import { useI18n } from "../i18n";

export function Pending({ memberships }: { memberships: Membership[] }) {
  const { t, label } = useI18n();
  return (
    <main className="hero" id="content" style={{ display: "block", maxWidth: 720 }}>
      <p className="kicker">{t("pending.kicker")}</p>
      <h1>{t("pending.title")}</h1>
      <p className="lead">{t("pending.lead")}</p>
      <ul className="card stack" aria-label={t("pending.list")}>
        {memberships.map((m) => (
          <li key={m.membership_id} style={{ listStyle: "none" }}>
            <strong>{label("role", m.role)}</strong> · {m.network_name ?? t("app.newOrganization")}{" "}
            <span className="chip">{t("app.pending")}</span>
          </li>
        ))}
      </ul>
      <button className="secondary" onClick={() => void signOut().then(() => window.location.assign("/"))}>{t("app.signOut")}</button>
    </main>
  );
}
