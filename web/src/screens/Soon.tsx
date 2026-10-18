import { useI18n } from "../i18n";

export function Soon({ title }: { title: string }) {
  const { t } = useI18n();
  return (
    <section aria-labelledby="soon-title">
      <h1 id="soon-title">{title}</h1>
      <p className="notice info">{t("soon.text")}</p>
    </section>
  );
}
