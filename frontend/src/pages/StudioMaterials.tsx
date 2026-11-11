import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowUpRight, Clapperboard, Plus } from "lucide-react";
import { api } from "../api";
import { useAccount } from "../account-context";
import { ErrorNotice, Loading } from "../components/common";
import { Button } from "../components/ui/button";
import {
  materialBase,
  formatNames,
  audioNames,
  type StudioMaterial,
} from "./studio-material";

export default function StudioMaterials({
  projectId,
  readOnly = false,
}: {
  projectId?: string;
  readOnly?: boolean;
}) {
  const { user } = useAccount();
  const [archived, setArchived] = useState(false);
  const materials = useInfiniteQuery({
    queryKey: ["studio-materials", user?.id, projectId, archived],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      api<StudioMaterial[]>(
        `${materialBase}?archived=${archived}&limit=30&offset=${pageParam}${projectId ? `&creative_project_id=${encodeURIComponent(projectId)}` : ""}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 30 ? pages.length * 30 : undefined,
  });
  const rows = materials.data?.pages.flat() ?? [];
  return (
    <section className="studio-material-browser" aria-label="Studio materials">
      <div className="studio-material-heading">
        <div>
          <span className="eyebrow">THE STORIES YOU'RE MAKING</span>
          <h2>Materials</h2>
        </div>
        {!readOnly && (
          <Button asChild>
            <Link
              to={`/studio/materials/new${projectId ? `?project=${projectId}` : ""}`}
            >
              <Plus size={16} />
              New material
            </Link>
          </Button>
        )}
      </div>
      <label className="studio-archived-toggle">
        <input
          type="checkbox"
          checked={archived}
          onChange={(e) => setArchived(e.target.checked)}
        />
        Show archived materials
      </label>
      <ErrorNotice error={materials.error} />
      {materials.isPending ? (
        <Loading />
      ) : rows.length ? (
        <div className="studio-material-grid">
          {rows.map((item) => (
            <Link
              key={item.id}
              className="studio-material-card"
              to={`/studio/materials/${item.id}`}
            >
              <span className="studio-material-kind">
                <Clapperboard size={16} />
                {formatNames[item.options.format]}
                <ArrowUpRight size={16} />
              </span>
              <h3>{item.title}</h3>
              <p>{item.brief}</p>
              <span className="studio-material-meta">
                {item.options.duration_seconds}s · {item.options.aspect} ·{" "}
                {audioNames[item.options.audio]}
              </span>
            </Link>
          ))}
        </div>
      ) : (
        !materials.error && (
          <div className="studio-material-start">
            <Clapperboard size={27} />
            <div>
              <h3>
                {archived ? "No archived materials" : "Start with an idea"}
              </h3>
              <p>
                A story, a lesson, a launch. Give it a brief and develop its
                script and shots in one place.
              </p>
            </div>
          </div>
        )
      )}
      {materials.hasNextPage && (
        <Button
          variant="secondary"
          disabled={materials.isFetchingNextPage}
          onClick={() => void materials.fetchNextPage()}
        >
          Show more materials
        </Button>
      )}
    </section>
  );
}
