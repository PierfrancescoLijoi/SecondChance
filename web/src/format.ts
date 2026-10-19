// Locale-aware formatting through the browser Intl API (FR-064): no hand-written date or number formats.

export function dateTime(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

export function timeRange(from: string, until: string, locale: string): string {
  const start = new Date(from);
  const end = new Date(until);
  const sameDay = start.toDateString() === end.toDateString();
  const endText = sameDay ? end.toLocaleTimeString(locale, { timeStyle: "short" }) : dateTime(until, locale);
  return `${dateTime(from, locale)} – ${endText}`;
}

export function kg(value: number | string, locale: string): string {
  return Number(value).toLocaleString(locale, { maximumFractionDigits: 1 });
}

export function percent(rate: number | null, locale: string): string | null {
  return rate === null ? null : rate.toLocaleString(locale, { style: "percent", maximumFractionDigits: 0 });
}

/** ISO weekday 1 (Monday) to 7 (Sunday) in the interface language. */
export function weekdayName(day: number, locale: string): string {
  return new Date(Date.UTC(2024, 0, day)).toLocaleDateString(locale, { weekday: "long", timeZone: "UTC" });
}

/** "08:00:00" from the API to "08:00" for time inputs. */
export function hhmm(time: string): string {
  return time.slice(0, 5);
}
