import { Link } from "react-router-dom";
import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Film, FileText } from "lucide-react";
import { api, type Artifact, type ArtifactLineage } from "../api";
import { ErrorNotice } from "../components/common";
import { useListKeyboard } from "./useListKeyboard";
import { artifactName } from "./artifactName";

function LineagePreview({ artifact }: { artifact: Artifact }) {
  if (artifact.type === "image") {
    return (
      <img
        src={`/api/artifacts/${artifact.id}/thumbnail`}
        alt=""
        loading="lazy"
      />
    );
  }
  const parentThumb =
    artifact.type === "video" && artifact.parent_artifact_ids[0]
      ? `/api/artifacts/${artifact.parent_artifact_ids[0]}/thumbnail`
      : "";
  return (
    <div className={`artifact-placeholder artifact-kind-${artifact.type}`}>
      {parentThumb ? (
        <img src={parentThumb} alt="" loading="lazy" />
      ) : artifact.type === "audio" ? (
        <AudioLines size={28} aria-hidden="true" />
      ) : artifact.type === "video" ? (
        <Film size={28} aria-hidden="true" />
      ) : (
        <FileText size={24} aria-hidden="true" />
      )}
    </div>
  );
}

export function LineageStrip({
  artifacts,
  role,
}: {
  artifacts: Artifact[];
  role: "source" | "derived";
}) {
  const headingId = useId();
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    artifacts,
    (artifact) => artifact.id,
  );
  const heading = role === "source" ? "Source artifacts" : "Derived artifacts";
  const noun = role === "source" ? "source" : "derived";
  if (!artifacts.length) return null;
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId}>{heading}</h3>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a {role === "source" ? "source" : "derived artifact"}{" "}
        while the list is focused. Enter inspects it. There is no inspectable
        lineage Run.
      </p>
      <div
        ref={listRef}
        className="lineage-strip"
        aria-labelledby={`${headingId} ${labelId}`}
        onKeyDown={onKeyDown}
      >
        {artifacts.map((related, i) => {
          const name = artifactName(related);
          const shortId = related.id.slice(0, 8);
          return (
            <Link
              key={related.id}
              to={`/library/${related.id}`}
              className="lineage-card"
              aria-label={`Inspect ${noun} ${name} ${shortId}`}
              {...itemProps(i, related.id)}
            >
              <LineagePreview artifact={related} />
              <strong>{name}</strong>
              <small>
                {related.type.replaceAll("_", " ")}
                {related.trashed_at ? " · Trash" : ""}
              </small>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function ArtifactLineageSections({
  sources,
  derived,
}: {
  sources: Artifact[];
  derived: Artifact[];
}) {
  const headingId = useId();
  if (!sources.length && !derived.length) return null;
  return (
    <section className="artifact-lineage" aria-labelledby={headingId}>
      <h2 id={headingId}>Lineage</h2>
      <LineageStrip artifacts={sources} role="source" />
      <LineageStrip artifacts={derived} role="derived" />
    </section>
  );
}

export function ArtifactLineage({ artifactId }: { artifactId: string }) {
  const query = useQuery({
    queryKey: ["artifact-lineage", artifactId],
    queryFn: () => api<ArtifactLineage>(`/artifacts/${artifactId}/lineage`),
  });
  return (
    <>
      <ErrorNotice error={query.error} />
      <ArtifactLineageSections
        sources={query.data?.sources ?? []}
        derived={query.data?.derived ?? []}
      />
    </>
  );
}
