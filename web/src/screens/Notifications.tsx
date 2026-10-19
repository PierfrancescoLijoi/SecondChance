import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, post, type AppNotification, type Inbox } from "../api";
import { dateTime } from "../format";
import { useI18n } from "../i18n";

const TARGETS: Record<AppNotification["object_type"], string> = {
  mission: "/missions",
  matching_run: "/matching",
  allocation_proposal: "/matching",
};

/** FR-026, in-app channel: each person sees only their own notifications (enforced by RLS). */
export function Notifications({ onChange }: { onChange?: () => void }) {
  const { t, label, locale } = useI18n();
  const [inbox, setInbox] = useState<Inbox | null>(null);

  const load = useCallback(() => {
    api<Inbox>("/notifications").then(setInbox).catch(() => setInbox({ unread: 0, items: [] }));
  }, []);
  useEffect(load, [load]);

  async function read(id: string | null) {
    await post(id ? `/notifications/${id}/read` : "/notifications/read-all").catch(() => undefined);
    load();
    onChange?.();
  }

  return (
    <section aria-labelledby="notifications-title" className="stack">
      <div className="toolbar">
        <h1 id="notifications-title">{t("notifications.title")}</h1>
        {inbox && inbox.unread > 0 && <button className="secondary" onClick={() => void read(null)}>{t("notifications.markAll")}</button>}
      </div>
      {inbox === null ? <p aria-busy="true">{t("app.loading")}</p> : inbox.items.length === 0 ? (
        <p className="notice info">{t("notifications.none")}</p>
      ) : (
        <ul className="plain stack">
          {inbox.items.map((n) => (
            <li key={n.id} className={`card notification${n.read_at ? "" : " unread"}`}>
              <p>
                {!n.read_at && <span className="chip">{t("notifications.unread")}</span>} {label("notification", n.kind)}
              </p>
              <p className="hint">{dateTime(n.created_at, locale)}</p>
              <div className="toolbar">
                <Link className="button secondary-link" to={TARGETS[n.object_type]} onClick={() => !n.read_at && void read(n.id)}>
                  {t("notifications.open")}
                </Link>
                {!n.read_at && <button className="secondary" onClick={() => void read(n.id)}>{t("notifications.markRead")}</button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Unread count for the top bar; refreshed every 30 seconds and when the inbox changes. */
export function useUnreadCount(enabled: boolean): [number, () => void] {
  const [count, setCount] = useState(0);
  const refresh = useCallback(() => {
    if (!enabled) return;
    api<Inbox>("/notifications?unread=true").then((inbox) => setCount(inbox.unread ?? 0)).catch(() => undefined);
  }, [enabled]);
  useEffect(() => {
    refresh();
    if (!enabled) return;
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [enabled, refresh]);
  return [count, refresh];
}
