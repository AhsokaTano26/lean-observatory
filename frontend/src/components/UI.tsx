import type { ReactNode } from "react";
import { Check, LoaderCircle, Clock3, AlertCircle } from "lucide-react";
import { statusLabels } from "../format";
import type { Status } from "../types";
export function Badge({ status }: { status: Status | string }) {
  return (
    <span className={`badge status-${status}`}>
      {status === "passed" ? (
        <Check size={11} />
      ) : status === "running" ? (
        <LoaderCircle size={11} />
      ) : status === "failed" || status === "resource_exhausted" ? (
        <AlertCircle size={11} />
      ) : (
        <Clock3 size={11} />
      )}{" "}
      {statusLabels[status] || status}
    </span>
  );
}
export function Panel({
  title,
  icon,
  aside,
  children,
  className = "",
}: {
  title: string;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <h2>
          {icon}
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
