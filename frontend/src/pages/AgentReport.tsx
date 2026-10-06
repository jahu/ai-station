import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Artifact } from "../api";
import { ErrorNotice, Loading } from "../components/common";

export default function AgentReport({ artifacts }: { artifacts: Artifact[] }) {
  const artifact = artifacts.find((item) => item.type === "markdown");
  const report = useQuery({
    queryKey: ["agent-report", artifact?.id],
    enabled: !!artifact,
    queryFn: async () => {
      const response = await fetch(`/api/artifacts/${artifact!.id}/file`);
      if (!response.ok) throw new Error("Could not load the agent report");
      return response.text();
    },
  });
  if (!artifact) return null;
  return (
    <section className="panel content-panel">
      <div className="row spread">
        <h2>
          {artifact.metadata?.partial ? "Partial report" : "Agent report"}
        </h2>
        <a
          className="text-link"
          href={`/api/artifacts/${artifact.id}/file`}
          target="_blank"
          rel="noreferrer"
        >
          Open report ↗
        </a>
      </div>
      <ErrorNotice error={report.error} />
      {report.isPending ? (
        <Loading />
      ) : (
        <div className="markdown">
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              img: ({ alt }) => <span>{alt ?? "Remote image omitted"}</span>,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            }}
          >
            {report.data ?? ""}
          </Markdown>
        </div>
      )}
    </section>
  );
}
