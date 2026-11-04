import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { ErrorNotice } from "../components/common";
import { Button } from "../components/ui/button";
import "./RegistryDeletion.css";

export type RegistryItem = { id: string; name: string; updated_at: string };
type Kind = "agents" | "projects";

export function useRegistryDeletion(
  kind: Kind,
  items: RegistryItem[],
  scope = "",
  onDeleted?: () => void,
) {
  const cache = useQueryClient();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const [selection, setSelection] = useState<{ scope: string; ids: string[] }>({
    scope,
    ids: [],
  });
  const [targets, setTargets] = useState<RegistryItem[]>([]);
  const ids = selection.scope === scope ? selection.ids : [];
  const selected = items.filter((item) => ids.includes(item.id));
  const noun = kind === "agents" ? "agent" : "project";
  const mutation = useMutation({
    mutationFn: () =>
      api<{ deleted: number }>(`/${kind}/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmed: true,
          items: targets.map(({ id, updated_at }) => ({
            id,
            expected_updated_at: updated_at,
          })),
        }),
      }),
    onSuccess: async () => {
      setTargets([]);
      setSelection({ scope, ids: [] });
      await Promise.all(
        [
          "agents",
          "agent",
          "projects",
          "project",
          "coding-projects",
          "dashboard",
        ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
      );
      onDeleted?.();
    },
    onError: () => {
      void cache.invalidateQueries({ queryKey: [kind] });
    },
  });
  const open = (rows: RegistryItem[], opener: HTMLElement) => {
    openerRef.current = opener;
    mutation.reset();
    setTargets(rows.map((item) => ({ ...item })));
  };
  return {
    rowActions: (item: RegistryItem, selectable = true) => (
      <div className="registry-row-actions">
        {selectable && (
          <label className="registry-select">
            <input
              type="checkbox"
              aria-label={`Select ${item.name}`}
              checked={ids.includes(item.id)}
              onChange={(event) =>
                setSelection({
                  scope,
                  ids: event.target.checked
                    ? [...ids, item.id]
                    : ids.filter((id) => id !== item.id),
                })
              }
            />
            Select
          </label>
        )}
        <Button
          variant="ghost"
          className="registry-delete"
          aria-label={`Delete ${item.name}`}
          onClick={(event) => open([item], event.currentTarget)}
        >
          <Trash2 size={15} aria-hidden="true" />
          Delete
        </Button>
      </div>
    ),
    toolbar: items.length > 0 && (
      <div
        className="toolbar registry-selection"
        aria-label={`Select ${kind} for deletion`}
      >
        <label className="registry-select">
          <input
            type="checkbox"
            aria-label={`Select all ${kind} on this page`}
            checked={selected.length === items.length}
            onChange={(event) =>
              setSelection({
                scope,
                ids: event.target.checked ? items.map((item) => item.id) : [],
              })
            }
          />
          Select page
        </label>
        <span className="muted">
          {selected.length
            ? `${selected.length} selected`
            : `${items.length} on this page`}
        </span>
        {selected.length > 0 && (
          <Button
            variant="secondary"
            className="registry-delete"
            onClick={(event) => open(selected, event.currentTarget)}
          >
            <Trash2 size={15} aria-hidden="true" />
            Delete selected ({selected.length})
          </Button>
        )}
      </div>
    ),
    dialog: (
      <Dialog.Root
        open={targets.length > 0}
        onOpenChange={(value) => {
          if (!value && !mutation.isPending) setTargets([]);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            className="registry-delete-dialog"
            onCloseAutoFocus={(event) => {
              if (openerRef.current?.isConnected) {
                event.preventDefault();
                openerRef.current.focus();
              }
            }}
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              cancelRef.current?.focus();
            }}
            onEscapeKeyDown={(event) => {
              if (mutation.isPending) event.preventDefault();
            }}
            onPointerDownOutside={(event) => {
              if (mutation.isPending) event.preventDefault();
            }}
          >
            <div className="registry-delete-icon">
              <Trash2 size={23} aria-hidden="true" />
            </div>
            <Dialog.Title>
              Delete{" "}
              {targets.length === 1
                ? `this ${noun}`
                : `${targets.length} ${kind}`}
              ?
            </Dialog.Title>
            <Dialog.Description>
              {kind === "agents"
                ? "These agents will leave your workspace and stop scheduling future work."
                : "These projects will leave your workspace. Linked agents will be paused and unlinked. Original folders, repositories and worktrees stay on disk."}{" "}
              Previous Runs, conversations and Library results are kept. This
              action cannot be undone here.
            </Dialog.Description>
            <ul className="registry-delete-names">
              {targets.map((item) => (
                <li key={item.id}>{item.name}</li>
              ))}
            </ul>
            <ErrorNotice error={mutation.error} />
            <div className="row registry-delete-footer">
              <Button
                ref={cancelRef}
                variant="secondary"
                disabled={mutation.isPending}
                onClick={() => setTargets([])}
              >
                Cancel
              </Button>
              <Button
                className="registry-confirm-delete"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate()}
              >
                {mutation.isPending
                  ? "Deleting…"
                  : targets.length === 1
                    ? `Delete ${noun}`
                    : `Delete ${targets.length} ${kind}`}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    ),
  };
}

export function RegistryDeleteButton({
  kind,
  item,
  onDeleted,
}: {
  kind: Kind;
  item: RegistryItem;
  onDeleted?: () => void;
}) {
  const deletion = useRegistryDeletion(kind, [item], item.id, onDeleted);
  return (
    <>
      {deletion.rowActions(item, false)}
      {deletion.dialog}
    </>
  );
}
