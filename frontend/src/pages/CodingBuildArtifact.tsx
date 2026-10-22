import { Download, PackageCheck, Monitor } from "lucide-react";
import { Link } from "react-router-dom";
import type { Run } from "../api";
import { Button } from "../components/ui/button";

export default function CodingBuildArtifact({ run }: { run?: Run }) {
  if (run?.status !== "succeeded") return null;
  const id = run.metadata?.build_artifact_id;
  const exported = run.metadata?.build_export as
    | {
        status?: string;
        file_count?: number;
        size_bytes?: number;
        reason?: string;
      }
    | undefined;
  if (typeof id !== "string" || exported?.status !== "ready") {
    return exported?.status === "unavailable" ? (
      <p className="muted coding-build-unavailable">
        Build download unavailable. {exported.reason}
      </p>
    ) : null;
  }
  const size =
    typeof exported.size_bytes === "number"
      ? `${(exported.size_bytes / 1024).toLocaleString("en-US", { maximumFractionDigits: 1 })} KB`
      : "ZIP archive";
  return (
    <section className="coding-build-artifact" aria-label="Build output">
      <div className="coding-build-heading">
        <PackageCheck size={20} aria-hidden="true" />
        <div>
          <strong>Build ready to download</strong>
          <small>
            {exported.file_count} {exported.file_count === 1 ? "file" : "files"}{" "}
            · {size} · captured after successful checks
          </small>
        </div>
      </div>
      <div className="coding-build-actions">
        <Button variant="secondary" asChild>
          <Link to={`/preview/${run.id}/${id}`}>
            <Monitor size={15} /> Preview website
          </Link>
        </Button>
        <Button variant="secondary" asChild>
          <a href={`/api/artifacts/${id}/file`} download="project-build.zip">
            <Download size={15} /> Download build
          </a>
        </Button>
        <Link className="text-link" to={`/library/${id}`}>
          View in Library →
        </Link>
      </div>
    </section>
  );
}
