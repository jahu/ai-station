import { Github } from "lucide-react";
export type GithubSnapshot = {
  run_id: string;
  captured_at: string;
  artifact_id: string;
  repository: string;
  issues: { number: number; title: string; url: string }[];
  pull_requests: {
    number: number;
    title: string;
    url: string;
    draft?: boolean;
  }[];
};
export default function GithubSnapshotResult({
  value,
}: {
  value: GithubSnapshot;
}) {
  return (
    <section
      className="content-panel github-repository-card"
      aria-label={`GitHub result ${value.repository}`}
    >
      <h4 className="row">
        <Github size={18} aria-hidden="true" /> {value.repository}
      </h4>
      <p className="muted">
        Captured {new Date(value.captured_at).toLocaleString()} · Read only
      </p>
      <div className="github-repository-lists">
        {(
          [
            ["Open issues", value.issues],
            ["Open pull requests", value.pull_requests],
          ] as const
        ).map(([label, items]) => (
          <section key={label} aria-label={`${label} snapshot`}>
            <h4>{label}</h4>
            {items.length ? (
              <ul className="github-entry-list">
                {items.map((item) => (
                  <li key={item.number}>
                    <a
                      className="text-link"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      #{item.number} {item.title}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">None in this snapshot.</p>
            )}
          </section>
        ))}
      </div>
      <a
        className="text-link"
        href={`/api/artifacts/${value.artifact_id}/file`}
        target="_blank"
        rel="noreferrer"
      >
        Download snapshot
      </a>
    </section>
  );
}
