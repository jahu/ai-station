import type { ReactNode } from "react";
import { AlertCircle, Inbox } from "lucide-react";

export function PageTitle({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
      {action}
    </div>
  );
}
export function ErrorNotice({ error }: { error: Error | null }) {
  return error ? (
    <div className="notice" role="alert">
      <AlertCircle size={17} />
      {error.message}
    </div>
  ) : null;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <Inbox size={28} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Badge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>
      <i />
      {status.replaceAll("_", " ")}
    </span>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      Connecting to your workstation…
    </div>
  );
}
export function Meter({
  value,
  total = 100,
}: {
  value: number | null;
  total?: number | null;
}) {
  const percent =
    value == null || !total
      ? 0
      : Math.max(0, Math.min(100, (value / total) * 100));
  return (
    <div
      className="meter"
      aria-label={
        value == null ? "No measurement" : `${Math.round(percent)} percent`
      }
    >
      <span style={{ width: `${percent}%` }} />
    </div>
  );
}
