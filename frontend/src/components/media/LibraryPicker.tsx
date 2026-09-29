import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useInfiniteQuery } from "@tanstack/react-query";
import { AudioLines, Check, Library, Search, X } from "lucide-react";
import { api, type Artifact } from "../../api";
import { ErrorNotice, Loading } from "../common";
import { Button } from "../ui/button";

export default function LibraryPicker({
  kind,
  existing,
  limit,
  busy,
  onSelect,
}: {
  kind: "image" | "audio";
  existing: string[];
  limit: number;
  busy: boolean;
  onSelect: (artifacts: Artifact[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [selected, setSelected] = useState<Artifact[]>([]);
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search.trim()), 200);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useInfiniteQuery({
    queryKey: ["library", "picker", kind, term],
    enabled: open,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<Artifact[]>(
        `/artifacts?${new URLSearchParams({ kind, search: term, limit: "40", offset: String(pageParam) })}`,
      ),
    getNextPageParam: (last, pages) =>
      last.length === 40 ? pages.length * 40 : undefined,
  });
  const available = (query.data?.pages.flat() ?? []).filter((a) =>
    kind === "audio"
      ? a.mime_type === "audio/wav"
      : ["image/png", "image/jpeg", "image/webp"].includes(a.mime_type),
  );
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (next) {
          setSearch("");
          setTerm("");
          setSelected([]);
        }
        setOpen(next);
      }}
    >
      <Dialog.Trigger asChild>
        <Button type="button" variant="ghost" disabled={busy || limit < 1}>
          <Library size={15} />{" "}
          {kind === "image" ? "Images from Library" : "Voice from Library"}
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="library-picker-dialog">
          <div className="library-dialog-heading">
            <Dialog.Title>
              {kind === "image"
                ? "Choose image references"
                : "Choose a voice recording"}
            </Dialog.Title>
            <Dialog.Close
              className="icon-button"
              aria-label="Close Library picker"
            >
              <X size={19} />
            </Dialog.Close>
          </div>
          <Dialog.Description>
            {kind === "image"
              ? "Select images in the order you want the assistant to use them. Existing files are reused without another upload."
              : "Select a PCM WAV recording for speech or portrait animation."}
          </Dialog.Description>
          <label className="model-search">
            <Search size={16} />
            <input
              aria-label="Search input Library"
              maxLength={200}
              placeholder="Search names and notes…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <ErrorNotice error={query.error} />
          {query.isPending ? (
            <Loading />
          ) : (
            <div
              className="library-picker-grid"
              role="group"
              aria-label="Reusable artifacts"
            >
              {available.map((a) => {
                const index = selected.findIndex((item) => item.id === a.id);
                const attached = existing.includes(a.id);
                return (
                  <button
                    type="button"
                    key={a.id}
                    className="library-picker-card"
                    aria-label={a.title || a.original_filename}
                    aria-pressed={index >= 0 || attached}
                    disabled={
                      busy ||
                      attached ||
                      (kind === "image" &&
                        selected.length >= limit &&
                        index < 0)
                    }
                    onClick={() =>
                      setSelected(
                        index >= 0
                          ? selected.filter((item) => item.id !== a.id)
                          : kind === "audio"
                            ? [a]
                            : [...selected, a],
                      )
                    }
                  >
                    {kind === "image" ? (
                      <img src={`/api/artifacts/${a.id}/thumbnail`} alt="" />
                    ) : (
                      <div className="library-picker-audio">
                        <AudioLines size={28} />
                      </div>
                    )}
                    <strong>{a.title || a.original_filename}</strong>
                    <small>
                      {attached
                        ? "Already attached"
                        : index >= 0
                          ? `Selected ${index + 1}`
                          : kind === "image"
                            ? `${a.metadata.width ?? "?"} × ${a.metadata.height ?? "?"}`
                            : "PCM WAV"}
                    </small>
                    {(index >= 0 || attached) && (
                      <span className="library-picker-check">
                        {attached ? <Check size={14} /> : index + 1}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
          {!query.isPending && !available.length && (
            <p className="model-empty">
              {term
                ? "No matching files. Try a different name or note."
                : "No compatible files in Library yet. Upload one in the composer."}
            </p>
          )}
          {query.hasNextPage && (
            <Button
              type="button"
              variant="ghost"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          )}
          <div className="library-dialog-footer">
            <span className="muted">
              {selected.length} selected{" "}
              {kind === "image" && `· up to ${limit}`}
            </span>
            <Button
              type="button"
              disabled={busy || !selected.length || selected.length > limit}
              onClick={() => {
                onSelect(selected);
                setOpen(false);
              }}
            >
              Attach{" "}
              {selected.length === 1 ? "file" : `${selected.length} files`}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
