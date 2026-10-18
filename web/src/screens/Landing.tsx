import { useEffect, useState } from "react";
import { devSignIn, signIn } from "../auth";
import { config } from "../config";
import { useI18n } from "../i18n";

type DemoUser = { subject: string; role: string };

export function Landing({ onSignedIn }: { onSignedIn: () => void }) {
  const { t } = useI18n();
  const isLocal = config().authMode === "mock";
  return (
    <main id="content">
      <section className="hero" aria-labelledby="hero-title">
        <div>
          <p className="kicker">{t("landing.kicker")}</p>
          <h1 id="hero-title">{t("landing.title")}</h1>
          <p className="lead">{t("landing.lead")}</p>
        </div>
        <div className="stack">
          <h2>{t("landing.enter")}</h2>
          {isLocal ? <DevLogin onSignedIn={onSignedIn} /> : <CloudLogin />}
        </div>
      </section>
      <ol className="steps" aria-label={t("landing.howItWorks")}>
        <li><strong>{t("landing.step1Title")}</strong><p className="muted">{t("landing.step1Text")}</p></li>
        <li><strong>{t("landing.step2Title")}</strong><p className="muted">{t("landing.step2Text")}</p></li>
        <li><strong>{t("landing.step3Title")}</strong><p className="muted">{t("landing.step3Text")}</p></li>
      </ol>
    </main>
  );
}

function CloudLogin() {
  const { t } = useI18n();
  return (
    <div className="card stack">
      <p>{t("landing.cloudText")}</p>
      <button onClick={() => void signIn()}>{t("landing.cloudButton")}</button>
    </div>
  );
}

function DevLogin({ onSignedIn }: { onSignedIn: () => void }) {
  const { t, label } = useI18n();
  const [users, setUsers] = useState<DemoUser[]>([]);
  const [subject, setSubject] = useState("");
  const [hasFailed, setHasFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${config().apiUrl}/dev/users`, { signal: controller.signal })
      .then((r) => r.json() as Promise<DemoUser[]>)
      .then(setUsers)
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const enter = (value: string) => devSignIn(value).then(onSignedIn).catch(() => setHasFailed(true));

  return (
    <div className="card stack">
      <p className="notice warn">{t("landing.devWarning")}</p>
      {hasFailed && <p className="notice error" role="alert">{t("landing.devSignInFailed")}</p>}
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void enter(subject.trim().toLowerCase());
        }}
      >
        <label htmlFor="new-subject">
          {t("landing.newUser")} <span className="hint">{t("landing.newUserHint")}</span>
        </label>
        <input id="new-subject" value={subject} onChange={(e) => setSubject(e.target.value)} pattern="[a-z0-9][a-z0-9-]{2,63}"
               placeholder={t("landing.newUserPlaceholder")} required />
        <button type="submit">{t("landing.newUserButton")}</button>
      </form>
      {users.length > 0 && (
        <fieldset>
          <legend>{t("landing.demoUsers")}</legend>
          <div className="stack">
            {users.map((u) => (
              <button key={u.subject} className="secondary block" onClick={() => void enter(u.subject)}>
                {label("role", u.role)} · {u.subject}
              </button>
            ))}
          </div>
        </fieldset>
      )}
    </div>
  );
}
