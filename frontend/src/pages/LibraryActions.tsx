import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2, RotateCcw, X } from "lucide-react";
import { api, type Artifact } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";

export default function LibraryActions({
  artifact,
  tabIndex,
}: {
  artifact: Artifact;
  tabIndex?: number;
}) {
  const [action, setAction] = useState<"edit" | "trash" | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [version, setVersion] = useState<string | null>(null);
  const cache = useQueryClient();
  const mutation = useMutation({
    mutationFn: ({
      operation,
      expected,
    }: {
      operation: "edit" | "trash" | "restore";
      expected: string | null;
    }) =>
      api<Artifact>(
        `/artifacts/${artifact.id}${operation === "restore" ? "/restore" : ""}`,
        {
          method:
            operation === "edit"
              ? "PATCH"
              : operation === "trash"
                ? "DELETE"
                : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_updated_at: expected,
            ...(operation === "edit" ? { title, notes } : {}),
          }),
        },
      ),
    onSuccess: (result) => {
      cache.setQueryData(["artifact", artifact.id], result);
      for (const key of [
        "library",
        "artifacts",
        "media-inputs",
        "dashboard",
        "artifact-lineage",
        "media-result",
      ])
        void cache.invalidateQueries({ queryKey: [key] });
      setAction(null);
    },
  });
  function open(next: "edit" | "trash") {
    mutation.reset();
    setVersion(artifact.library_updated_at ?? null);
    setTitle((artifact.title || artifact.original_filename).slice(0, 200));
    setNotes(artifact.notes ?? "");
    setAction(next);
  }
  const shortId = artifact.id.slice(0, 8);
  return (
    <>
      <div className="library-detail-actions">
        <Button
          variant="secondary"
          tabIndex={tabIndex}
          aria-label={`Edit details ${shortId}`}
          onClick={() => open("edit")}
        >
          <Pencil size={15} />
          Edit details
        </Button>
        {artifact.trashed_at ? (
          <Button
            variant="secondary"
            tabIndex={tabIndex}
            disabled={mutation.isPending}
            aria-label={`Restore to Library ${shortId}`}
            onClick={() =>
              mutation.mutate({
                operation: "restore",
                expected: artifact.library_updated_at ?? null,
              })
            }
          >
            <RotateCcw size={15} />
            Restore to Library
          </Button>
        ) : (
          <Button
            variant="ghost"
            tabIndex={tabIndex}
            aria-label={`Move to Trash ${shortId}`}
            onClick={() => open("trash")}
          >
            <Trash2 size={17} />
          </Button>
        )}
      </div>
      {!action && <ErrorNotice error={mutation.error} />}
      <Dialog.Root
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) setAction(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="library-dialog">
            <div className="library-dialog-heading">
              <Dialog.Title>
                {action === "edit" ? "Edit artifact details" : "Move to Trash?"}
              </Dialog.Title>
              <Dialog.Close className="icon-button" aria-label="Close">
                <X size={18} />
              </Dialog.Close>
            </div>
            <Dialog.Description>
              {action === "edit"
                ? "Give this artifact a recognizable name and keep your own notes. Generation details stay intact."
                : "This hides the artifact from your Library and input pickers. Its file and run history are kept, and you can restore it anytime."}
            </Dialog.Description>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (action)
                  mutation.mutate({ operation: action, expected: version });
              }}
            >
              {action === "edit" ? (
                <>
                  <label>
                    Display name
                    <input
                      autoFocus
                      maxLength={200}
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder={artifact.original_filename}
                    />
                  </label>
                  <label>
                    Notes
                    <textarea
                      rows={4}
                      maxLength={4000}
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                      placeholder="What would you like to remember about this artifact?"
                    />
                  </label>
                </>
              ) : (
                <p className="library-trash-name">
                  {artifact.title || artifact.original_filename}
                </p>
              )}
              <ErrorNotice error={mutation.error} />
              <div className="library-dialog-footer">
                <Dialog.Close asChild>
                  <Button type="button" variant="ghost">
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button
                  type="submit"
                  disabled={mutation.isPending}
                  className={action === "trash" ? "library-trash-confirm" : ""}
                >
                  {mutation.isPending
                    ? "Saving…"
                    : action === "edit"
                      ? "Save details"
                      : "Move to Trash"}
                </Button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
