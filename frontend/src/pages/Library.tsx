import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Artifact } from "../api";
import { Empty, ErrorNotice, Loading, PageTitle } from "../components/common";
import { Button } from "../components/ui/button";
import { time } from "../lib/utils";

export function ArtifactCards({ artifacts }: { artifacts: Artifact[] }) {
  return (
    <div className="artifact-grid">
      {artifacts.map((a) => (
        <Link
          className="artifact-card panel"
          key={a.id}
          to={`/library/${a.id}`}
        >
          {a.type === "image" ? (
            <img
              loading="lazy"
              src={`/api/artifacts/${a.id}/thumbnail`}
              alt={a.original_filename}
            />
          ) : (
            <div className="artifact-placeholder">{a.type}</div>
          )}
          <div>
            <strong>
              {a.metadata.mode
                ? ({
                    t2i: "Generate",
                    img2img: "Edit",
                    recompose: "Recompose",
                    upscale: "Upscale",
                  }[a.metadata.mode] ?? a.metadata.mode)
                : a.original_filename}
            </strong>
            <span>
              {a.metadata.backend ?? a.type}
              {a.metadata.width
                ? ` · ${a.metadata.width} × ${a.metadata.height}`
                : ""}
            </span>
            <small>{time(a.created_at)}</small>
          </div>
        </Link>
      ))}
    </div>
  );
}
export function Library() {
  const query = useQuery({
    queryKey: ["artifacts"],
    queryFn: () => api<Artifact[]>("/artifacts"),
    refetchInterval: 5000,
  });
  return (
    <>
      <PageTitle
        eyebrow="COLLECTION / ARTIFACTS"
        title="Your creative library."
        action={
          <Button asChild>
            <Link to="/images">Create an image</Link>
          </Button>
        }
      >
        Generated images, speech and source uploads, with their history intact.
        Latest 100 artifacts.
      </PageTitle>
      <ErrorNotice error={query.error} />
      {query.isPending ? (
        <Loading />
      ) : query.data?.length ? (
        <ArtifactCards artifacts={query.data} />
      ) : (
        <section className="panel">
          <Empty title="Your library starts here">
            Upload a source image or create your first image in the Images
            workspace.
          </Empty>
        </section>
      )}
    </>
  );
}
export function ArtifactDetail() {
  const { id } = useParams();
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<Error | null>(null);
  const query = useQuery({
    queryKey: ["artifact", id],
    queryFn: () => api<Artifact>(`/artifacts/${id}`),
  });
  const a = query.data;
  const prompt =
    a?.metadata.edit_prompt || a?.metadata.prompt || a?.metadata.text || "";
  return (
    <>
      <Link className="back-link" to="/library">
        ← Library
      </Link>
      <PageTitle
        eyebrow="COLLECTION / INSPECTOR"
        title={a?.original_filename ?? "Artifact"}
      >
        Source, parameters, and execution history.
      </PageTitle>
      <ErrorNotice error={query.error ?? copyError} />
      {query.isPending ? (
        <Loading />
      ) : (
        a && (
          <div className="image-workspace">
            <section className="panel artifact-preview">
              {a.type === "image" && (
                <img
                  src={`/api/artifacts/${a.id}/file`}
                  alt={prompt || a.original_filename}
                />
              )}
              {a.type === "audio" && (
                <audio
                  controls
                  preload="metadata"
                  src={`/api/artifacts/${a.id}/file`}
                  aria-label="Generated audio"
                />
              )}
              <a
                href={`/api/artifacts/${a.id}/file`}
                target="_blank"
                rel="noreferrer"
              >
                Open full artifact ↗
              </a>
            </section>
            <aside className="panel content-panel">
              <h2>Artifact details</h2>
              <p>
                {a.metadata.width
                  ? `${a.metadata.width} × ${a.metadata.height} · `
                  : ""}
                {(a.size_bytes / 1024).toFixed(0)} KiB
              </p>
              <p className="muted">{time(a.created_at)}</p>
              {a.type === "image" && (
                <div className="artifact-actions">
                  {[
                    ["img2img", "Edit"],
                    ["recompose", "Recompose"],
                    ["upscale", "Upscale"],
                  ].map(([mode, label]) => (
                    <Button key={mode} asChild variant="secondary">
                      <Link to={`/images?mode=${mode}&input=${a.id}`}>
                        {label}
                      </Link>
                    </Button>
                  ))}
                </div>
              )}
              {a.type === "audio" && (
                <Button asChild variant="secondary">
                  <Link to={`/audio?input=${a.id}`}>
                    Use as voice reference
                  </Link>
                </Button>
              )}
              {prompt && (
                <>
                  <h3>{a.type === "audio" ? "Spoken text" : "Prompt"}</h3>
                  <p className="prompt-text">{prompt}</p>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(prompt)
                        .then(() => setCopied(true))
                        .catch(() =>
                          setCopyError(
                            new Error(
                              "Clipboard unavailable. Select and copy the prompt text.",
                            ),
                          ),
                        );
                    }}
                  >
                    {copied
                      ? "Copied"
                      : a.type === "audio"
                        ? "Copy text"
                        : "Copy prompt"}
                  </Button>
                </>
              )}
              {a.run_id && (
                <p>
                  <Link to={`/runs/${a.run_id}`}>Inspect source run →</Link>
                </p>
              )}
              {a.parent_artifact_ids.length > 0 && (
                <>
                  <h3>Source artifacts</h3>
                  <div className="source-strip">
                    {a.parent_artifact_ids.map((parent) => (
                      <Link key={parent} to={`/library/${parent}`}>
                        {a.type === "image" ? (
                          <img
                            src={`/api/artifacts/${parent}/thumbnail`}
                            alt={`Source ${parent.slice(0, 8)}`}
                          />
                        ) : (
                          `Reference ${parent.slice(0, 8)} →`
                        )}
                      </Link>
                    ))}
                  </div>
                </>
              )}
              <details>
                <summary>All parameters</summary>
                <pre>{JSON.stringify(a.metadata, null, 2)}</pre>
              </details>
            </aside>
          </div>
        )
      )}
    </>
  );
}
