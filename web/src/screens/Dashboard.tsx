import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard as DashboardData } from "../api";
import { kg, percent, dateTime } from "../format";
import { useI18n } from "../i18n";
import type { MessageKey } from "../locales/en";

const WINDOWS = [7, 30, 90];

/** FR-052/FR-053: aggregates only; no person is identifiable from anything on this screen. */
export function Dashboard() {
  const { t, label, locale } = useI18n();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DashboardData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    api<DashboardData>(`/dashboard?days=${days}`)
      .then((d) => active && setData(d))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [days]);

  const na = t("dashboard.notAvailable");
  const tiles: { label: MessageKey; value: string; hint?: string; to?: string }[] = data
    ? [
        { label: "dashboard.offersPublished", value: String(data.offers.published),
          hint: t("dashboard.kgPublished", { kg: kg(data.offers.kg_published, locale) }) },
        { label: "dashboard.kgReceived", value: `${kg(data.impact.kg_received, locale)} kg`,
          hint: t("dashboard.receipts", { confirmed: String(data.impact.receipts_confirmed),
                                          exceptions: String(data.impact.receipt_exceptions) }) },
        { label: "dashboard.openMissions", value: String(data.missions.open), to: "/missions" },
        { label: "dashboard.openProposals", value: String(data.matching.open_proposals), to: "/matching" },
        { label: "dashboard.medianAllocation", value: data.missions.median_allocation_hours === null ? na
            : t("dashboard.hours", { hours: kg(data.missions.median_allocation_hours, locale) }) },
        { label: "dashboard.onTimeRate", value: percent(data.missions.on_time_rate, locale) ?? na },
        { label: "dashboard.failureRate", value: percent(data.missions.failure_rate, locale) ?? na },
        { label: "dashboard.approvalRate", value: percent(data.matching.approval_rate, locale) ?? na },
        { label: "dashboard.expired", value: String(data.offers.expired) },
        { label: "dashboard.emailPending", value: String(data.notifications.email_pending) },
      ]
    : [];

  return (
    <section aria-labelledby="dashboard-title" className="stack">
      <div className="toolbar">
        <h1 id="dashboard-title">{t("dashboard.title")}</h1>
        <label className="inline">
          {t("dashboard.window")}{" "}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {WINDOWS.map((d) => <option key={d} value={d}>{t("dashboard.days", { days: String(d) })}</option>)}
          </select>
        </label>
      </div>
      <p className="muted">{t("dashboard.intro")}</p>
      {failed && <p className="notice error" role="alert">{t("app.unexpectedError")}</p>}
      {!data && !failed && <p aria-busy="true">{t("app.loading")}</p>}
      {data && (
        <>
          <ul className="tiles" aria-label={t("dashboard.title")}>
            {tiles.map((tile) => (
              <li key={tile.label} className="tile">
                <span className="tile-label">{t(tile.label)}</span>
                <strong className="tile-value">{tile.to ? <Link to={tile.to}>{tile.value}</Link> : tile.value}</strong>
                {tile.hint && <span className="hint">{tile.hint}</span>}
              </li>
            ))}
          </ul>

          <div className="grid-2">
            <article className="card">
              <h2>{t("dashboard.centres")}</h2>
              {data.centres.length === 0 ? <p className="muted">{t("common.none")}</p> : (
                <table>
                  <thead><tr><th scope="col">{t("dashboard.centre")}</th><th scope="col">{t("dashboard.utilisation")}</th></tr></thead>
                  <tbody>
                    {data.centres.map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}{c.status === "paused" && <> <span className="chip">{label("centerStatus", c.status)}</span></>}</td>
                        <td>
                          <meter min={0} max={c.capacity_kg} value={c.committed_today_kg} low={c.capacity_kg * 0.7}
                                 high={c.capacity_kg * 0.9} optimum={0} aria-label={c.name} />{" "}
                          <span className="hint">{kg(c.committed_today_kg, locale)} / {kg(c.capacity_kg, locale)} kg</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </article>
            <article className="card">
              <h2>{t("dashboard.missionsByStatus")}</h2>
              {Object.keys(data.missions.by_status).length === 0 ? <p className="muted">{t("common.none")}</p> : (
                <ul className="plain">
                  {Object.entries(data.missions.by_status).map(([status, count]) => (
                    <li key={status}><span className="chip">{label("missionStatus", status)}</span> {count}</li>
                  ))}
                </ul>
              )}
              <h2 style={{ marginTop: "1rem" }}>{t("dashboard.lastRun")}</h2>
              {data.matching.last_run ? (
                <p>
                  <span className="chip">{label("matchingStatus", data.matching.last_run.status)}</span>{" "}
                  {dateTime(data.matching.last_run.created_at, locale)} ·{" "}
                  {t("dashboard.lastRunSummary", { proposals: String(data.matching.last_run.proposals ?? 0),
                                                    unassigned: String(data.matching.last_run.unassigned) })}
                </p>
              ) : <p className="muted">{t("dashboard.noRun")}</p>}
            </article>
          </div>

          <article className="card">
            <h2>{t("dashboard.categories")}</h2>
            {data.categories.length === 0 ? <p className="muted">{t("common.none")}</p> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{t("offers.category")}</th><th scope="col">{t("dashboard.offered")}</th>
                      <th scope="col">{t("dashboard.received")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.categories.map((c) => (
                      <tr key={c.category}>
                        <td>{label("category", c.category)}</td><td>{kg(c.kg_offered, locale)}</td><td>{kg(c.kg_received, locale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        </>
      )}
    </section>
  );
}
