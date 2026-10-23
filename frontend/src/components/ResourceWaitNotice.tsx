import { Clock3 } from "lucide-react";
import { Link } from "react-router-dom";
import type { ResourceWait } from "../api";

const gib = (mib: number) => `${(mib / 1024).toFixed(1)} GiB`;

export default function ResourceWaitNotice({
  wait,
}: {
  wait?: ResourceWait | null;
}) {
  if (!wait) return null;
  const checked = new Date(wait.checked_at);
  return (
    <section className="notice resource-wait-notice" aria-label="Resource wait">
      <strong className="row">
        <Clock3 size={16} aria-hidden="true" />
        {wait.reason === "memory"
          ? "Waiting for memory"
          : "Waiting for an available GPU"}
      </strong>
      {wait.reason === "memory" && (
        <p>
          RAM needed: {gib(wait.required_mib)} · Available when checked:{" "}
          {wait.available_mib == null ? "Unknown" : gib(wait.available_mib)}.
          {wait.reserved_mib > 0 &&
            ` Other active Runs reserve ${gib(wait.reserved_mib)}.`}
          {wait.headroom_mib > 0 &&
            ` Safety headroom: ${gib(wait.headroom_mib)}.`}
        </p>
      )}
      <p className="muted">
        AI Station will retry automatically. You can leave this page or stop the
        task.
      </p>
      <small className="muted">
        {!Number.isNaN(checked.getTime()) && (
          <>Last checked {checked.toLocaleTimeString()} · </>
        )}
        <Link className="text-link" to={`/runs/${wait.run_id}`}>
          Inspect waiting Run
        </Link>
      </small>
    </section>
  );
}
