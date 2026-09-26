import { Link } from "react-router-dom";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import type { Run } from "../api";

type Review = {
  branch: string;
  files: {
    path: string;
    diff: string;
    insertions: number;
    deletions: number;
  }[];
};

export default function CodingReview({ run }: { run: Run }) {
  const next = run.metadata?.coding_run_id;
  const validation = run.metadata?.validation_run_id;
  const review = run.metadata?.coding_review as Review | undefined;
  if (!next && !review && run.metadata?.execution_location !== "external")
    return null;
  return (
    <section className="panel content-panel">
      <span className="chip">EXTERNAL CURSOR AI</span>
      {typeof next === "string" && (
        <p>
          <Link className="text-link" to={`/runs/${next}`}>
            Open Cursor execution →
          </Link>
        </p>
      )}
      {review && (
        <>
          <h2 className="mt">Changes awaiting review</h2>
          <p className="mono">{review.branch}</p>
          <p>
            Agent completion is not a correctness verdict. Review the changes
            and validation before integrating this branch.
          </p>
          {typeof validation === "string" ? (
            <p>
              <Link className="text-link" to={`/runs/${validation}`}>
                Inspect validation results →
              </Link>
            </p>
          ) : (
            <p className="notice">
              No validation commands were configured. This proposal has not been
              tested.
            </p>
          )}
          {!review.files.length && <p>No file contents changed.</p>}
          {review.files.map((file) => (
            <details key={file.path} open>
              <summary>
                {file.path} · +{file.insertions} / −{file.deletions}
              </summary>
              <div className="markdown">
                <Markdown
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    img: () => null,
                    a: ({ children }) => <span>{children}</span>,
                  }}
                >
                  {"````````````diff\n" + file.diff + "\n````````````"}
                </Markdown>
              </div>
            </details>
          ))}
        </>
      )}
    </section>
  );
}
