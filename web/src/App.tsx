import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError, selectedTenant, type Me, type Membership } from "./api";
import { completeSignIn, currentToken, signOut } from "./auth";
import { I18nProvider, LanguagePicker, useI18n } from "./i18n";
import { screensFor } from "./nav";
import { Assistant } from "./screens/Assistant";
import { Documents } from "./screens/Documents";
import { Knowledge } from "./screens/Knowledge";
import { Landing } from "./screens/Landing";
import { NewOffer } from "./screens/NewOffer";
import { Offers } from "./screens/Offers";
import { Pending } from "./screens/Pending";
import { Register } from "./screens/Register";
import { Registrations } from "./screens/Registrations";
import { Soon } from "./screens/Soon";

type State =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "error"; message: string | null }
  | { kind: "ready"; me: Me };

export function App() {
  return (
    <I18nProvider>
      <Session />
    </I18nProvider>
  );
}

function Session() {
  const { t } = useI18n();
  const [state, setState] = useState<State>({ kind: "loading" });
  const location = useLocation();
  const navigate = useNavigate();

  const refresh = useCallback(async () => {
    if (!(await currentToken())) return setState({ kind: "anonymous" });
    try {
      setState({ kind: "ready", me: await api<Me>("/me") });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return setState({ kind: "anonymous" });
      setState({ kind: "error", message: error instanceof ApiError ? error.message : null });
    }
  }, []);

  useEffect(() => {
    if (location.pathname === "/callback") {
      completeSignIn()
        .then(() => navigate("/", { replace: true }))
        .then(refresh)
        .catch(() => setState({ kind: "error", message: t("app.signInIncomplete") }));
      return;
    }
    void refresh();
  }, []); // once at start-up: refresh and navigate are stable for this mount

  if (state.kind === "loading") return <Public><p className="hero" aria-busy="true">{t("app.loading")}</p></Public>;
  if (state.kind === "error") {
    return <Public><p className="hero notice error" role="alert">{state.message ?? t("app.unexpectedError")}</p></Public>;
  }
  if (state.kind === "anonymous") return <Public><Landing onSignedIn={refresh} /></Public>;

  const active = state.me.memberships.filter((m) => m.status === "active");
  if (active.length === 0) {
    const pending = state.me.memberships.filter((m) => m.status === "pending");
    return <Public>{pending.length > 0 ? <Pending memberships={pending} /> : <Register onRegistered={refresh} />}</Public>;
  }
  return <Shell memberships={active} onChange={refresh} />;
}

/** Pages before the user has a role: brand and language choice only. */
function Public({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="topbar">
        <a className="brand" href="/">SecondChance</a>
        <span className="spacer" />
        <LanguagePicker />
      </header>
      {children}
    </>
  );
}

function Shell({ memberships, onChange }: { memberships: Membership[]; onChange: () => void }) {
  const { t, label } = useI18n();
  const stored = selectedTenant.get();
  const current = memberships.find((m) => m.tenant_id === stored) ?? memberships[0];
  if (current.tenant_id !== stored) selectedTenant.set(current.tenant_id);
  const screens = screensFor(current.capabilities);
  const has = (...capabilities: string[]) => capabilities.some((c) => current.capabilities.includes(c));

  return (
    <>
      <a className="skip-link" href="#content">{t("app.skipToContent")}</a>
      <header className="topbar">
        <a className="brand" href="/">SecondChance</a>
        <span className="chip">{label("role", current.role)}</span>
        <span className="spacer" />
        {memberships.length > 1 ? (
          <label>
            <span className="visually-hidden">{t("app.network")}</span>
            <select
              value={current.tenant_id}
              onChange={(event) => {
                selectedTenant.set(event.target.value);
                onChange();
              }}
            >
              {memberships.map((m) => (
                <option key={m.tenant_id} value={m.tenant_id}>{m.network_name ?? t("app.network")}</option>
              ))}
            </select>
          </label>
        ) : (
          <span>{current.network_name ?? t("app.platform")}</span>
        )}
        <LanguagePicker />
        <button className="secondary" onClick={() => void signOut().then(() => window.location.assign("/"))}>{t("app.signOut")}</button>
      </header>
      <div className="shell">
        <nav className="sidenav" aria-label={t("app.features")}>
          {screens.map((screen) => (
            <NavLink key={screen.path} to={screen.path} end>
              {t(screen.label)}
              {screen.soon && <span className="soon">{t("app.soon")}</span>}
            </NavLink>
          ))}
        </nav>
        <main id="content" tabIndex={-1}>
          <Routes>
            {has("assistant") && <Route path="/assistant" element={<Assistant canRunAgents={has("agents.run")} />} />}
            {has("offers.view", "offers.own") && (
              <Route path="/offers" element={<Offers canReserve={has("offers.reserve")} isDonor={has("offers.own")} />} />
            )}
            {has("offers.create") && <Route path="/offers/new" element={<NewOffer />} />}
            {has("knowledge.search") && <Route path="/knowledge" element={<Knowledge />} />}
            {has("documents.manage") && <Route path="/documents" element={<Documents tenantId={current.tenant_id} />} />}
            {has("registrations.review", "networks.review") && (
              <Route path="/registrations" element={<Registrations platform={has("networks.review")} />} />
            )}
            {has("missions.own") && <Route path="/missions" element={<Soon title={t("nav.missions")} />} />}
            {has("center.manage") && <Route path="/center" element={<Soon title={t("nav.center")} />} />}
            <Route path="*" element={<Navigate to={screens[0]?.path ?? "/"} replace />} />
          </Routes>
        </main>
      </div>
    </>
  );
}
